"""Conservative local PDF-to-rating pipeline. No model or network dependency."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .engine import rate_policy
from .models import AnalysisDecision, PolicyInput, SourceRef
from .parsers.pdf import parse_pdf
from .insurer_rules import apply_insurer_rules
from . import review

CONFIDENCE_FLOOR = 0.72


@dataclass(frozen=True)
class ExtractedFact:
    value: Any
    page: int
    confidence: float
    text: str
    source: SourceRef
    label: str | None = None


@dataclass
class StructuredPolicyFacts:
    insurer: ExtractedFact | None = None
    previous_insurer: ExtractedFact | None = None
    business_type: ExtractedFact | None = None
    policy_type: ExtractedFact | None = None
    policy_start_date: ExtractedFact | None = None
    fuel: ExtractedFact | None = None
    engine_cc: ExtractedFact | None = None
    manufacture_year: ExtractedFact | None = None
    registration_year: ExtractedFact | None = None
    rto: ExtractedFact | None = None
    state: ExtractedFact | None = None
    registration_number: ExtractedFact | None = None
    make: ExtractedFact | None = None
    model: ExtractedFact | None = None
    make_model: ExtractedFact | None = None
    od_premium: ExtractedFact | None = None
    tp_premium: ExtractedFact | None = None
    net_premium: ExtractedFact | None = None
    basic_od_premium: ExtractedFact | None = None
    basic_tp_premium: ExtractedFact | None = None
    ncb_discount_amount: ExtractedFact | None = None
    total_addon_premium: ExtractedFact | None = None
    add_ons: ExtractedFact | None = None
    total_package_premium: ExtractedFact | None = None
    integrated_tax: ExtractedFact | None = None
    total_premium: ExtractedFact | None = None
    ncb_percent: ExtractedFact | None = None
    ncb_eligibility: ExtractedFact | None = None
    ncb_state: ExtractedFact | None = None
    conflicts: dict[str, list[ExtractedFact]] = field(default_factory=dict)
    low_confidence: dict[str, list[ExtractedFact]] = field(default_factory=dict)
    missing_or_uncertain: list[str] = field(default_factory=list)


@dataclass
class DocumentDecision:
    document_name: str
    document_sha256: str
    page_count: int
    ocr_pages: list[int]
    ocr_pages_limited: bool
    facts: StructuredPolicyFacts
    policy_input: PolicyInput
    decision: AnalysisDecision
    extraction_metadata: dict[str, Any] = field(default_factory=dict)


def _lines(parsed: dict[str, Any]):
    for page in parsed["pages"]:
        n = page["page_number"]
        if page.get("ocr_lines"):
            for line in page["ocr_lines"]:
                yield n, str(line["text"]), float(line.get("confidence", 0.0))
        else:
            for line in page.get("text", "").splitlines():
                if line.strip():
                    yield n, line.strip(), 1.0


def _fact(parsed, page, text, confidence, value, label=None):
    return ExtractedFact(value, page, confidence, text,
                         SourceRef(parsed["document_name"], parsed["sha256"], page=page,
                                   role="ocr_extracted_policy_fact"), label)


def _label_value_candidates(parsed, label_pattern, value_pattern, converter, *, max_y_delta=6.0):
    """Read explicitly labeled OCR fields using line coordinates, not text order.

    Scanned schedules often place a label and its value in separate OCR boxes on
    the same row. The source line and label are both retained in the fact.
    """
    label_re = re.compile(label_pattern, re.I)
    value_re = re.compile(value_pattern, re.I)
    candidates = []
    for page in parsed["pages"]:
        ocr_lines = page.get("ocr_lines") or []
        for label_line in ocr_lines:
            label_text = str(label_line.get("text", "")).strip()
            label_match = label_re.search(label_text)
            if not label_match:
                continue
            label = label_text[:label_match.end()].strip(" :\t-")
            remainder = label_text[label_match.end():].strip(" :\t-")
            inline = value_re.fullmatch(remainder)
            choices = []
            if inline:
                choices.append((0.0, float(label_line.get("x", 0)), label_line, inline.group(0), label_line))
            else:
                label_x = float(label_line.get("x", 0))
                label_y = float(label_line.get("y", 0))
                for value_line in ocr_lines:
                    value_text = str(value_line.get("text", "")).strip()
                    if value_line is label_line or float(value_line.get("x", 0)) <= label_x + 2:
                        continue
                    delta_y = abs(float(value_line.get("y", 0)) - label_y)
                    if delta_y > max_y_delta:
                        continue
                    matched = value_re.fullmatch(value_text)
                    if matched:
                        choices.append((delta_y, float(value_line.get("x", 0)) - label_x,
                                        value_line, matched.group(0), label_line))
            if not choices:
                continue
            choices.sort(key=lambda item: (item[0], item[1]))
            best = choices[0]
            # Two equally positioned, valid values are conflicting evidence;
            # retain both rather than choosing based on OCR reading order.
            tied = [item for item in choices if abs(item[0] - best[0]) < 0.1 and abs(item[1] - best[1]) < 0.1]
            for _, _, value_line, raw_value, source_label_line in tied:
                try:
                    value = converter(raw_value)
                except (TypeError, ValueError):
                    continue
                page_number = int(page["page_number"])
                source_label = str(source_label_line.get("text", "")).strip()
                source_value = str(value_line.get("text", "")).strip()
                source_text = source_label if source_label_line is value_line else f"{source_label}: {source_value}"
                confidence = min(float(source_label_line.get("confidence", 0.0)),
                                 float(value_line.get("confidence", 0.0)))
                candidates.append(_fact(parsed, page_number, source_text, confidence, value, label))
    return candidates


def _assign_candidates(out, field_name, candidates):
    confident = [fact for fact in candidates if fact.confidence >= CONFIDENCE_FLOOR]
    values = {str(fact.value) for fact in confident}
    if len(values) == 1:
        # Policy schedule page 1 is the preferred source when a proposal form
        # repeats the same value later in the document.
        setattr(out, field_name, min(confident, key=lambda fact: (fact.page, -fact.confidence)))
    elif len(values) > 1:
        out.conflicts[field_name] = confident
    elif candidates:
        out.low_confidence[field_name] = candidates


def _page_match(parsed, patterns, converter=lambda m: m.group(1), page_filter=None):
    """Match explicit labels across OCR line breaks, retaining the containing page."""
    for page in parsed["pages"]:
        n = page["page_number"]
        if page_filter is not None and n not in page_filter:
            continue
        text = page.get("text", "")
        for pattern in patterns:
            m = re.search(pattern, text, re.I | re.S)
            if m:
                raw = m.group(0)
                confs = [float(line.get("confidence", 1.0)) for line in page.get("ocr_lines", [])
                         if any(token.casefold() in line["text"].casefold()
                                for token in re.findall(r"[A-Za-z0-9]+", raw) if len(token) > 3)]
                confidence = min(confs) if confs else (0.80 if page.get("ocr_used") else 1.0)
                try:
                    value = converter(m)
                except (ValueError, IndexError):
                    continue
                return n, raw.strip(), confidence, value
    return None


def _search(lines, pattern, converter=lambda m: m.group(1), confidence_floor=CONFIDENCE_FLOOR):
    regex = re.compile(pattern, re.I)
    for page, text, conf in lines:
        match = regex.search(text)
        if match:
            try:
                value = converter(match)
            except (ValueError, IndexError):
                continue
            return page, text, conf, value
    return None


def extract_structured_facts(parsed: dict[str, Any]) -> StructuredPolicyFacts:
    lines = list(_lines(parsed))
    out = StructuredPolicyFacts()

    insurer_names = [
        ("hdfc-ergo", r"HDFC\s*ERGO|HDFC ERGO GENERAL"),
        ("godigit", r"GO\s*DIGIT|DIGIT GENERAL INSURANCE"),
        ("reliance-indusind", r"RELIANCE(?:\s*GENERAL|\s*INSURANCE)?"),
        ("tata-aig", r"TATA\s*AIG|TATA AIG GENERAL"),
    ]
    # Current insurer comes from the document masthead/issuer area, never from
    # whole-document occurrence counts (which include prior-insurer references).
    header_regions = []
    for page in parsed["pages"]:
        if page.get("ocr_lines"):
            header_lines = [line for line in page["ocr_lines"] if float(line.get("y", 0)) <= 150][:35]
            header_text = "\n".join(line["text"] for line in header_lines)
            line_items = [(page["page_number"], line["text"], float(line.get("confidence", 0.0))) for line in header_lines]
        else:
            header_text = "\n".join(page.get("text", "").splitlines()[:15])
            line_items = [(page["page_number"], line, 1.0) for line in header_text.splitlines()]
        header_regions.append((page["page_number"], header_text, line_items))
    found = []
    for name, pattern in insurer_names:
        hits = []
        for page_number, header_text, line_items in header_regions:
            hit = _search(line_items, pattern, lambda _: name)
            issuer_match = re.search(r"(?:issued\s+by|insurer|insurance\s+company|general\s+insurance|policy\s+schedule)[^\n]{0,100}", header_text, re.I)
            if not hit and issuer_match and re.search(pattern, issuer_match.group(0), re.I):
                hit = (page_number, issuer_match.group(0), 0.80, name)
            if hit:
                hits.append(hit)
                break
        if hits:
            found.append((name, hits[0]))
    if not found:
        # Some issuers put the legal company name in a signed schedule/footer
        # while the masthead contains only a short brand. Accept that identity
        # only on a page that also carries an explicit policy product title.
        for name, pattern in insurer_names:
            for page in parsed["pages"]:
                page_text = page.get("text", "")
                has_title = bool(re.search(
                    r"(?:private\s*car\s*(?:package|comprehensive)|auto\s*secure\s*[-–]?\s*liability\s*only)\s*policy",
                    page_text, re.I))
                if not has_title:
                    continue
                footer_line = next((line for line in page.get("ocr_lines", [])
                                    if re.search(pattern, line["text"], re.I)
                                    and re.search(r"GENERAL\s*INSURANCE|TATAAIG", line["text"], re.I)), None)
                if footer_line:
                    found.append((name, (page["page_number"], footer_line["text"],
                                         float(footer_line.get("confidence", 0.0)), name)))
                    break
    if found:
        if len(found) == 1:
            p, t, c, v = found[0][1]
            out.insurer = _fact(parsed, p, t, c, v)
        else:
            out.conflicts["insurer"] = [_fact(parsed, *hit) for _, hit in found]

    # Product is selected only from explicit policy-title/product/schedule language.
    # Generic third-party/liability coverage clauses are not product selectors.
    product_hits = []
    for page in parsed["pages"]:
        page_text = page.get("text", "")
        satp = re.search(r"(?:digit\s*)?private\s*car\s*liability\s*only\s*policy|standalone\s*tp\s*policy|auto\s*secure\s*[-–]?\s*liability\s*only\s*policy", page_text, re.I)
        package = re.search(r"(?:private\s*car\s*)?(?:package|comprehensive(?:\s*package)?)\s*(?:motor\s*)?policy", page_text, re.I)
        if satp:
            product_hits.append(_fact(parsed, page["page_number"], satp.group(0), 0.80 if page.get("ocr_used") else 1.0, "Standalone TP"))
        if package:
            product_hits.append(_fact(parsed, page["page_number"], package.group(0), 0.80 if page.get("ocr_used") else 1.0, "Private Car Package"))
    products = {fact.value for fact in product_hits}
    if len(products) == 1:
        out.policy_type = product_hits[0]
    elif len(products) > 1:
        out.conflicts["policy_type"] = product_hits

    fuel_hits = []
    for p, t, c in lines:
        m = re.search(r"(?:fuel\s*type|fuel)\s*[:\-]?\s*(petrol|diesel|cng|lpg|electric|ev|hybrid)\b", t, re.I)
        if m:
            fuel_hits.append(_fact(parsed, p, t, c, m.group(1).upper() if m.group(1).upper() in {"CNG", "LPG", "EV"} else m.group(1).title()))
    fuel_values = {f.value.casefold() for f in fuel_hits if f.confidence >= CONFIDENCE_FLOOR}
    if len(fuel_values) == 1:
        out.fuel = next(f for f in fuel_hits if f.confidence >= CONFIDENCE_FLOOR)
    elif len(fuel_values) > 1:
        out.conflicts["fuel"] = fuel_hits
    if not fuel_hits:
        hit = _page_match(parsed, [r"FUEL\s*TYPE\s*[:\-]?\s*(PETROL|DIESEL|CNG|LPG|ELECTRIC|EV|HYBRID)\b"],
                          lambda m: m.group(1).title() if m.group(1).upper() not in {"CNG", "LPG", "EV"} else m.group(1).upper())
        if hit:
            p, t, c, v = hit
            out.fuel = _fact(parsed, p, t, c, v) if c >= CONFIDENCE_FLOOR else None
    if out.fuel is None and "fuel" not in out.conflicts:
        for page in parsed["pages"]:
            labels = [line for line in page.get("ocr_lines", []) if re.search(r"^Fuel\s*Type$", line["text"], re.I)]
            for label in labels:
                options = []
                for line in page.get("ocr_lines", []):
                    m = re.fullmatch(r"\s*(Petrol|Diesel|CNG|LPG|Electric|EV|Hybrid)\s*", line["text"], re.I)
                    if m and abs(float(line["y"]) - float(label["y"])) < 18:
                        options.append((abs(float(line["y"]) - float(label["y"])), line, m.group(1)))
                if len(options) == 1:
                    _, line, value = options[0]
                    value = value.upper() if value.upper() in {"CNG", "LPG", "EV"} else value.title()
                    out.fuel = _fact(parsed, page["page_number"], f"{label['text']} / {line['text']}",
                                     min(float(label["confidence"]), float(line["confidence"])), value)
                    break

    number = r"[0-9][0-9,]*(?:\.[0-9]{1,2})?"
    spatial_specs = [
        ("make", r"^Make$", r"[A-Z][A-Z0-9& .()/\-]{1,50}", str),
        ("model", r"^Model$", r"[A-Z0-9][A-Z0-9 .()/\-]{1,70}", str),
        ("registration_number", r"^Registration\s+No\.?$", r"[A-Z]{2}\s*-\s*[0-9]{1,2}\s*-\s*[A-Z]{1,3}\s*-\s*[0-9]{1,4}", str),
        ("rto", r"^RTO$", r"[A-Z][A-Z .'-]{2,40}", lambda raw: re.sub(r"\s+", " ", raw).strip()),
        ("engine_cc", r"^Cubic\s+Capacity(?:\s+Watts)?$", r"[0-9]{2,5}", int),
        ("manufacture_year", r"^Year\s*of\s*Manufacture", r"(?:19|20)[0-9]{2}", int),
        ("basic_od_premium", r"^Basic\s+Own\s+Damage$", number, lambda raw: Decimal(raw.replace(",", ""))),
        ("ncb_discount_amount", r"^Less:\s*No\s+Claim\s+Bonus\s*\(\s*[0-9]{1,2}(?:\.[0-9]+)?\s*%\s*\)$", number, lambda raw: Decimal(raw.replace(",", ""))),
        ("basic_tp_premium", r"^Basic\s+Third\s+Party\s+Liability$", number, lambda raw: Decimal(raw.replace(",", ""))),
        ("tp_premium", r"^Net\s+Liability\s+Premium\s*\(b\)$", number, lambda raw: Decimal(raw.replace(",", ""))),
        ("total_addon_premium", r"^Total\s*-\s*Add\s*on$", number, lambda raw: Decimal(raw.replace(",", ""))),
        ("total_package_premium", r"^Total\s+Package\s+Premium\s*\(a\s*\+\s*b\)$", number, lambda raw: Decimal(raw.replace(",", ""))),
        ("integrated_tax", r"^Integrated\s+Tax\s*18\s*%$", number, lambda raw: Decimal(raw.replace(",", ""))),
        ("total_premium", r"^Total\s*Premium$", number, lambda raw: Decimal(raw.replace(",", ""))),
        ("od_premium", r"^(?:Net|Total)\s+Own\s+Damage\s+Premium\s*\(a\)$", number, lambda raw: Decimal(raw.replace(",", ""))),
    ]
    for name, label_pattern, value_pattern, convert in spatial_specs:
        _assign_candidates(out, name, _label_value_candidates(parsed, label_pattern, value_pattern, convert))

    # Text-layer PDFs may expose explicitly labeled values inline. Never use an
    # unlabelled monetary amount or a basic/add-on amount as net premium.
    for name, pattern, converter in (
        ("engine_cc", r"(?:Cubic\s+Capacity(?:\s+Watts)?|Engine\s*(?:Capacity|CC))\s*[:\-]?\s*([0-9,]{2,5})", lambda m: int(m.group(1).replace(",", ""))),
        ("manufacture_year", r"(?:Year\s*of\s*Manufacture|Manufacture\s*Year|MFG\.?\s*Year)\s*[:\-]?\s*((?:19|20)[0-9]{2})", lambda m: int(m.group(1))),
        ("od_premium", r"(?:Net|Total)\s+Own\s+Damage\s+Premium\s*\(a\)\s*[:\s\u20b9]*([0-9,]+(?:\.[0-9]{1,2})?)", lambda m: Decimal(m.group(1).replace(",", ""))),
        ("tp_premium", r"Net\s+Liability\s+Premium\s*\(b\)\s*[:\s\u20b9]*([0-9,]+(?:\.[0-9]{1,2})?)", lambda m: Decimal(m.group(1).replace(",", ""))),
        ("registration_number", r"Registration\s*(?:No\.?|Number)\s*[:\-]?\s*([A-Z]{2}[\s-]*[0-9]{1,2}[\s-]*[A-Z]{0,3}[\s-]*[0-9]{1,4})\b",
         lambda m: re.sub(r"[\s-]+", "", m.group(1)).upper()),
    ):
        if getattr(out, name) is not None or name in out.conflicts:
            continue
        hit = _page_match(parsed, [pattern], converter)
        if hit:
            p, source_text, confidence, value = hit
            setattr(out, name, _fact(parsed, p, source_text, confidence, value))

    # A schedule can print several explicitly labelled OD totals. Retain all of
    # them as a conflict instead of letting a first-match fallback silently pick
    # one; the layout rules can then supply the cited net premium.
    if out.od_premium is None and "od_premium" not in out.conflicts:
        od_candidates = []
        for page, text, confidence in lines:
            match = re.search(
                r"(?:Net|Total)\s+Own\s+Damage\s+Premium(?:\s*\(a\))?\s*[:\s\u20b9]*([0-9,]+(?:\.[0-9]{1,2})?)",
                text, re.I,
            )
            if match:
                od_candidates.append(_fact(
                    parsed, page, text, confidence,
                    Decimal(match.group(1).replace(",", "")),
                ))
        _assign_candidates(out, "od_premium", od_candidates)

    # Preserve make and model separately and as a combined display/rating fact.
    if out.make and out.model and out.make.page == out.model.page:
        out.make_model = _fact(parsed, out.make.page,
                               f"{out.make.text}; {out.model.text}",
                               min(out.make.confidence, out.model.confidence),
                               f"{out.make.value} {out.model.value}", "Make / Model")
    if out.engine_cc is None and "engine_cc" not in out.conflicts:
        hit = _page_match(parsed, [r"(?:CUBIC\s+CAPACITY|CC\s*/\s*HP|ENGINE\s+CAPACITY)\s*[:\-]?\s*([0-9,]{3,5})\s*(?:CC)?"],
                          lambda m: int(m.group(1).replace(",", "")))
        if hit:
            p, t, c, v = hit
            out.engine_cc = _fact(parsed, p, t, c, v) if c >= CONFIDENCE_FLOOR else None
    if out.manufacture_year is None:
        hit = _page_match(parsed, [r"(?:YEAR\s+OF\s+MFG\.?|MFG\.?\s*(?:MONTH\s*&\s*)?YEAR)\s*[:\-]?\s*(?:[A-Z]{3}[- ]*)?(20\d{2}|19\d{2})"], lambda m: int(m.group(1)))
        if hit:
            p, t, c, v = hit
            out.manufacture_year = _fact(parsed, p, t, c, v) if c >= CONFIDENCE_FLOOR else None

    ncb_hits = []
    for p, t, c in lines:
        if re.search(r"NCB|NO CLAIM BONUS", t, re.I):
            for m in re.finditer(r"(\d{1,2}(?:\.\d+)?)\s*%", t):
                ncb_hits.append(_fact(parsed, p, t, c, Decimal(m.group(1))))
    for page in parsed["pages"]:
        page_text = page.get("text", "")
        for m in re.finditer(r"(?:No Claim Bonus|NCB)[^\n]{0,40}?(\d{1,2}(?:\.\d+)?)\s*%", page_text, re.I):
            ncb_hits.append(_fact(parsed, page["page_number"], m.group(0), 0.80, Decimal(m.group(1))))
        for m in re.finditer(r"Valid\s*(\d{1,2}(?:\.\d+)?)\s*%", page_text, re.I):
            out.ncb_eligibility = _fact(parsed, page["page_number"], m.group(0), 0.80,
                                        f"valid, stated {m.group(1)}%")
    ncb_hits = list({(f.page, str(f.value), f.text): f for f in ncb_hits}.values())
    ncb_values = {str(f.value) for f in ncb_hits if f.confidence >= CONFIDENCE_FLOOR}
    if len(ncb_values) == 1:
        out.ncb_percent = next(f for f in ncb_hits if f.confidence >= CONFIDENCE_FLOOR)
    elif len(ncb_values) > 1:
        out.conflicts["ncb_percent"] = ncb_hits

    for page in parsed["pages"]:
        labels = [line for line in page.get("ocr_lines", []) if re.search(r"^RTO\s*Location\s*:?$", line["text"], re.I)]
        for label in labels:
            options = []
            for line in page.get("ocr_lines", []):
                value = line["text"].strip()
                if (value and not re.search(r"RTO|Location|Premium|Engine|Policy|Zone|CC/HP|Seating|Capacity", value, re.I)
                        and re.search(r"[A-Za-z]{3,}", value)
                        and not re.fullmatch(r"[\d,.\s₹]+", value)
                        and abs(float(line["y"]) - float(label["y"])) < 18):
                    options.append((abs(float(line["y"]) - float(label["y"])), line))
            if options:
                _, match = min(options, key=lambda item: item[0])
                out.rto = _fact(parsed, page["page_number"], f"{label['text']} / {match['text']}",
                                min(float(label["confidence"]), float(match["confidence"])), match["text"].strip())
                break
        if out.rto:
            break
    if out.rto is None:
        for p, t, c in lines:
            m = re.search(r"(?:RTO|REGISTRATION\s+LOCATION)\s*[:\-]?\s*((?:HR|UP|DL|KA|MH|TN|GJ|WB|RJ|PB|AP|TS|KL|MP|CG|OD|BR|JH|UK|HP|AS)[- ]?\d{1,2})\b", t, re.I)
            if m:
                out.rto = _fact(parsed, p, t, c, m.group(1))
                break
    if out.rto is None:
        hit = _page_match(parsed, [r"RTO\s+Location\s*[:\-]?\s*([^\n]{3,80})"], lambda m: m.group(1).strip())
        if hit:
            p, t, c, v = hit
            if c >= CONFIDENCE_FLOOR and re.search(r"[A-Za-z]{3,}", v) and not re.fullmatch(r"[\d,.\s₹]+", v):
                out.rto = _fact(parsed, p, t, c, v)

    # Previous insurer is read only in the explicit previous-insurer section.
    for page in parsed["pages"]:
        text = page.get("text", "")
        marker = re.search(r"Previous\s*Insurer", text, re.I)
        if marker:
            tail = text[marker.end():marker.end() + 1200]
            prior = _search([(page["page_number"], tail, 0.95)],
                            r"(HDFC\s*ERGO(?:\s+General Insurance)?|Go\s*Digit General Insurance Limited|Go\s*Digit General Insurance Ltd\.?|Reliance General Insurance|Tata\s*AIG(?: General Insurance)?)",
                            lambda m: m.group(1))
            if prior:
                p, t, c, v = prior
                out.previous_insurer = _fact(parsed, p, t, c, v.strip())
            else:
                explicit = re.search(r"Previous\s*Insurer\s*[:\-]\s*([^\n]{4,100})", text, re.I)
                if explicit:
                    out.previous_insurer = _fact(parsed, page["page_number"], explicit.group(0),
                                                 0.80 if page.get("ocr_used") else 1.0,
                                                 explicit.group(1).strip())
            break

    hit = _page_match(parsed, [r"Model/Vehicle Variant\s*\n\s*([^\n]{3,100})"], page_filter=None)
    if hit:
        p, t, c, v = hit
        out.make_model = _fact(parsed, p, t, c, v.strip()) if c >= CONFIDENCE_FLOOR else None

    for field_name in ("insurer", "policy_type", "fuel", "engine_cc", "rto"):
        fact = getattr(out, field_name)
        if fact is None:
            out.missing_or_uncertain.append(f"{field_name} missing or not confidently extracted")
        elif fact.confidence < CONFIDENCE_FLOOR:
            out.missing_or_uncertain.append(f"{field_name} OCR confidence below {CONFIDENCE_FLOOR:.2f}")
    for field_name, candidates in (("fuel", fuel_hits),):
        low = [fact for fact in candidates if fact.confidence < CONFIDENCE_FLOOR]
        if low:
            out.low_confidence[field_name] = low
            out.missing_or_uncertain.append(f"{field_name} has OCR candidates below confidence {CONFIDENCE_FLOOR:.2f}")
    for field_name in ("insurer", "policy_type", "engine_cc", "manufacture_year", "rto", "od_premium", "tp_premium", "ncb_percent"):
        fact = getattr(out, field_name)
        if fact is not None and fact.confidence < CONFIDENCE_FLOOR:
            out.low_confidence.setdefault(field_name, []).append(fact)
            out.missing_or_uncertain.append(f"{field_name} has a low-confidence OCR candidate")
    for name, candidates in out.conflicts.items():
        out.missing_or_uncertain.append(f"{name} has conflicting values: " + ", ".join(str(f.value) for f in candidates))
    return out


# Indian registration marks begin with the state's code (Motor Vehicles Act
# schedule), so a printed registration number identifies the registration state
# and RTO code even when the schedule does not print them separately.
REGISTRATION_STATES = {
    "AN": "Andaman and Nicobar Islands", "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh",
    "AS": "Assam", "BR": "Bihar", "CG": "Chhattisgarh", "CH": "Chandigarh", "DD": "Daman and Diu",
    "DL": "Delhi", "DN": "Dadra and Nagar Haveli", "GA": "Goa", "GJ": "Gujarat", "HP": "Himachal Pradesh",
    "HR": "Haryana", "JH": "Jharkhand", "JK": "Jammu and Kashmir", "KA": "Karnataka", "KL": "Kerala",
    "LA": "Ladakh", "LD": "Lakshadweep", "MH": "Maharashtra", "ML": "Meghalaya", "MN": "Manipur",
    "MP": "Madhya Pradesh", "MZ": "Mizoram", "NL": "Nagaland", "OD": "Odisha", "OR": "Odisha",
    "PB": "Punjab", "PY": "Puducherry", "RJ": "Rajasthan", "SK": "Sikkim", "TN": "Tamil Nadu",
    "TR": "Tripura", "TS": "Telangana", "UK": "Uttarakhand", "UA": "Uttarakhand",
    "UP": "Uttar Pradesh", "WB": "West Bengal",
}
_REGISTRATION_MARK = re.compile(
    r"^\s*([A-Z]{2})[\s-]*([0-9]{1,2})[\s-]*([A-Z]{1,3})(?:[\s-]*([A-Z]{1,3}))?[\s-]*[0-9]{1,4}\s*$", re.I)


def _registration_parts(registration: Any) -> tuple[str | None, str | None]:
    """Return (state name, RTO code such as 'UP78' or 'DL9C') from a registration mark."""
    match = _REGISTRATION_MARK.match(str(registration or ""))
    if not match:
        return None, None
    code, district, series, second_series = match.groups()
    state = REGISTRATION_STATES.get(code.upper())
    if not state:
        return None, None
    # Delhi-style marks (DL 9C AB 2893) carry a one-letter series in the RTO code.
    if second_series and len(series) == 1:
        return state, f"{code}{int(district)}{series}".upper()
    if code.upper() == "DL" and not second_series and len(series) == 3:
        return state, f"{code}{int(district)}{series[0]}".upper()  # 'DL9CAB2893' -> DL9C
    return state, f"{code}{int(district):02d}".upper()


def _year(value: Any) -> int | None:
    match = re.search(r"\b(19[5-9][0-9]|20[0-9]{2})\b", str(value or ""))
    return int(match.group(1)) if match else None


_REGISTRATION_TOKEN = re.compile(r"\b([A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4})\b")


def _fallback_registration_number(parsed: dict[str, Any], facts: StructuredPolicyFacts) -> None:
    """OCR often emits a registration mark away from its label. When no labelled
    value was found, accept the mark that clearly dominates the pages that
    mention "Registration" (e.g. repeated in every page footer)."""
    if facts.registration_number is not None or "registration_number" in facts.conflicts:
        return
    counts: dict[str, int] = {}
    first_page: dict[str, int] = {}
    for page in parsed["pages"]:
        text = page.get("text") or ""
        if not re.search(r"registration", text, re.I):
            continue
        for mark in _REGISTRATION_TOKEN.findall(text.upper()):
            if _registration_parts(mark)[1]:
                counts[mark] = counts.get(mark, 0) + 1
                first_page.setdefault(mark, page["page_number"])
    if not counts:
        return
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    if len(ranked) > 1 and ranked[0][1] < 2 * ranked[1][1]:
        return
    mark = ranked[0][0]
    facts.registration_number = _fact(parsed, first_page[mark], mark, 0.8, mark,
                                      "Vehicle Registration No. (OCR, most frequent mark)")


def _derive_registration_state(parsed: dict[str, Any], facts: StructuredPolicyFacts) -> None:
    if facts.state is not None or "state" in facts.conflicts or facts.registration_number is None:
        return
    registration = facts.registration_number
    state, _ = _registration_parts(registration.value)
    if state:
        facts.state = _fact(parsed, registration.page, registration.text, registration.confidence,
                            state, "Registration state (from registration number)")


def normalize_policy_input(facts: StructuredPolicyFacts) -> PolicyInput:
    def val(name):
        fact = getattr(facts, name)
        return fact.value if fact is not None and fact.confidence >= CONFIDENCE_FLOOR and name not in facts.conflicts else None

    # Vehicle age is measured at the start of the current policy period. A
    # registration year stands in only when no plausible manufacture year exists.
    start_year = _year(val("policy_start_date"))
    built_year = _year(val("manufacture_year"))
    age_source = "manufacture_year"
    if built_year is None or (start_year is not None and built_year > start_year):
        built_year, age_source = _year(val("registration_year")), "registration_year"
    vehicle_age = start_year - built_year if start_year is not None and built_year is not None and start_year >= built_year else None
    _, rto_code = _registration_parts(val("registration_number"))
    add_ons = val("add_ons")

    refs: dict[str, list[SourceRef]] = {}
    if vehicle_age is not None:
        refs["vehicle_age_years"] = [facts.policy_start_date.source, getattr(facts, age_source).source]
    if rto_code:
        refs["rto_code"] = [facts.registration_number.source]
    for name in ("insurer", "previous_insurer", "business_type", "policy_type", "fuel", "engine_cc", "rto", "state", "make", "model", "od_premium", "tp_premium", "net_premium", "basic_od_premium", "basic_tp_premium", "ncb_discount_amount", "total_addon_premium", "add_ons", "total_package_premium", "integrated_tax", "total_premium", "ncb_percent", "ncb_state"):
        fact = getattr(facts, name)
        if fact:
            refs[name] = [fact.source]
        if name in facts.conflicts:
            refs[name] = [candidate.source for candidate in facts.conflicts[name]]
    return PolicyInput(
        insurer=val("insurer"), previous_insurer=val("previous_insurer"), business_type=val("business_type"),
        policy_type=val("policy_type"), cover=val("policy_type"), fuel=val("fuel"),
        engine_cc=val("engine_cc"), vehicle_age_years=vehicle_age,
        make=(val("make") or val("make_model")), model=val("model"),
        rto=val("rto"), rto_code=rto_code, geography=val("state"),
        od_premium=val("od_premium"), tp_premium=val("tp_premium"), net_premium=val("net_premium"),
        basic_od_premium=val("basic_od_premium"), basic_tp_premium=val("basic_tp_premium"),
        ncb_discount_amount=val("ncb_discount_amount"), add_on_premium=val("total_addon_premium"),
        add_ons=tuple(add_ons) if add_ons else None,
        total_package_premium=val("total_package_premium"), gst=val("integrated_tax"),
        total_premium_including_tax=val("total_premium"), ncb_percent=val("ncb_percent"),
        ncb_state=val("ncb_state"),
        source_evidence=refs)


def document_to_decision(path: str | Path, *, rate_card_root: str | Path | None = None) -> DocumentDecision:
    """Extract and rate one policy without any AI service.

    Text comes from the PDF text layer or, for scanned pages, local OCR
    (RapidOCR). Facts are read by deterministic label/value rules plus
    insurer-specific schedule rules; anything not printed is left for the
    reviewer to supply rather than guessed.
    """
    parsed = parse_pdf(path)
    facts = extract_structured_facts(parsed)
    apply_insurer_rules(parsed, facts)
    _fallback_registration_number(parsed, facts)
    _derive_registration_state(parsed, facts)
    if parsed.get("ocr_pages_limited"):
        facts.missing_or_uncertain.append(
            "Some scanned pages were beyond the OCR page limit (LOCAL_OCR_MAX_PAGES).")
    metadata = {"status": "completed", "engine": "local",
                "ocr_pages": [page["page_number"] for page in parsed["pages"] if page.get("ocr_used")]}
    policy = normalize_policy_input(facts)
    decision = rate_policy(policy, rate_card_root) if rate_card_root else rate_policy(policy)
    return DocumentDecision(parsed["document_name"], parsed["sha256"], parsed["page_count"],
                            [page["page_number"] for page in parsed["pages"] if page.get("ocr_used")],
                            parsed.get("ocr_pages_limited", False), facts, policy, decision, metadata)


def result_dict(result: DocumentDecision) -> dict[str, Any]:
    def fact_dict(fact):
        if fact is None:
            return None
        value = ", ".join(map(str, fact.value)) if isinstance(fact.value, (list, tuple)) else str(fact.value)
        return {"value": value, "page": fact.page, "confidence": fact.confidence,
                "text": fact.text, "source": asdict(fact.source)}

    return {
        "document": {"name": result.document_name, "sha256": result.document_sha256,
                     "page_count": result.page_count, "ocr_pages": result.ocr_pages,
                     "ocr_pages_limited": result.ocr_pages_limited},
        "facts": {name: fact_dict(getattr(result.facts, name)) for name in (
            "insurer", "previous_insurer", "business_type", "policy_type", "fuel", "engine_cc", "manufacture_year",
            "rto", "state", "registration_number", "make_model", "policy_start_date", "registration_year",
            "od_premium", "tp_premium", "net_premium", "add_ons", "ncb_percent", "ncb_eligibility", "ncb_state")},
        "conflicts": {k: [fact_dict(f) for f in values] for k, values in result.facts.conflicts.items()},
        "low_confidence": {k: [fact_dict(f) for f in values] for k, values in result.facts.low_confidence.items()},
        "missing_or_uncertain": result.facts.missing_or_uncertain,
        "assessment_status": review.assessment_status(result.decision, result.ocr_pages_limited),
        "ai_extraction": result.extraction_metadata,
        # Extracted inputs (with evidence) are kept so a reviewer can correct them and re-rate.
        "policy_input": review.policy_to_dict(result.policy_input),
        "rating_inputs": review.rating_inputs(result.policy_input),
        "overrides": {},
        "rating_trace": result.decision.trace,
        "totals": review.totals(result.decision),
        "decisions": {"overall": result.decision.status.value,
                      "OD": decision_dict(result.decision.od), "TP": decision_dict(result.decision.tp)},
    }


def decision_dict(decision):
    return {"status": decision.status.value, "applicable": decision.applicable,
            "rate_percent": str(decision.rate_percent) if decision.rate_percent is not None else None,
            "commission_amount": str(decision.commission_amount) if decision.commission_amount is not None else None,
            "premium_basis": str(decision.premium_basis) if decision.premium_basis is not None else None,
            "rate_basis": decision.rate_basis, "selected_conditions": decision.selected_conditions,
            "calculation": decision.calculation,
            "evidence": [asdict(ref) for ref in decision.evidence], "issues": decision.issues}
    