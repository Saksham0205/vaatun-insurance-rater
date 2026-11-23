"""Layout-aware rule extraction for scanned motor policy schedules (no AI).

OCR returns each text line with its position. Schedules are label/value tables,
so a value is the text on the same row to the right of its label, or directly
beneath it. Matching by position is far more reliable than reading OCR text in
order, where table cells from different columns interleave.

Every rule fills a fact only when the deterministic text parser left it empty
or conflicting, and each extracted value keeps the page and the exact OCR text
it came from as evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable


MONEY = re.compile(r"^-?(?:Rs\.?|₹)?\s*([0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]+)(?:\.[0-9]{1,2})?$")
YEAR = re.compile(r"\b(19[5-9][0-9]|20[0-4][0-9])\b")
REG_MARK = re.compile(r"\b([A-Z]{2})[\s-]*([0-9]{1,2})[\s-]*([A-Z]{1,3})[\s-]*([0-9]{3,4})\b")
FUELS = {"petrol": "Petrol", "diesel": "Diesel", "cng": "CNG", "lpg": "LPG", "electric": "Electric",
         "battery": "Electric", "ev": "Electric", "hybrid": "Hybrid"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"], 1)}
KNOWN_MAKES = ("MARUTI SUZUKI", "MARUTI", "HYUNDAI", "TATA", "MAHINDRA", "HONDA", "TOYOTA", "KIA", "RENAULT",
               "NISSAN", "FORD", "VOLKSWAGEN", "SKODA", "MG", "JEEP", "BMW", "MERCEDES BENZ", "MERCEDES-BENZ",
               "AUDI", "VOLVO", "CHEVROLET", "FIAT", "DATSUN", "CITROEN", "BYD", "ISUZU", "LEXUS", "JAGUAR",
               "LAND ROVER", "PORSCHE", "MINI")


INSURER_NAMES = {"godigit": "Go Digit General Insurance Ltd.", "hdfc-ergo": "HDFC ERGO General Insurance Co. Ltd.",
                 "reliance-indusind": "Reliance General Insurance Co. Ltd.",
                 "tata-aig": "Tata AIG General Insurance Co. Ltd."}

STOP = object()  # parser verdict: this label's value is a placeholder; do not look further


@dataclass
class Hit:
    value: Any
    page: int
    text: str
    confidence: float
    label: str


def _lines(page: dict[str, Any]) -> list[dict[str, Any]]:
    if page.get("ocr_lines"):
        return page["ocr_lines"]
    # Text-layer page: synthesize positions so the same rules apply row by row.
    return [{"text": t, "x": 0.0, "y": float(i * 10), "confidence": 0.99}
            for i, t in enumerate((page.get("text") or "").splitlines()) if t.strip()]


def _money(text: str) -> Decimal | None:
    cleaned = text.replace(" ", "").replace("(₹)", "").replace("₹", "").replace("Rs.", "").strip()
    match = MONEY.match(cleaned)
    if not match:
        return None
    try:
        return Decimal(cleaned.replace(",", "").lstrip("-")).quantize(Decimal("0.01")).normalize()
    except InvalidOperation:
        return None


def _neighbours(lines, label, *, max_dy=5.0, max_dx=560.0, below_dy=18.0, below_dx=90.0, below=True):
    """Lines on the label's row to its right (nearest first), then lines just below it."""
    lx, ly = label["x"], label["y"]
    width = max(len(label["text"]) * 4.5, 20)
    row = sorted((l for l in lines if l is not label and abs(l["y"] - ly) <= max_dy
                  and lx + width * 0.5 < l["x"] <= lx + max_dx), key=lambda l: l["x"])
    under = sorted((l for l in lines if l is not label and 0 < l["y"] - ly <= below_dy
                    and abs(l["x"] - lx) <= below_dx), key=lambda l: (l["y"], abs(l["x"] - lx))) if below else []
    return row + under


def find(parsed, label_pattern: str, parse: Callable[[str], Any], *, pages=None, inline: bool = True,
         below: bool = True, max_dx: float = 560.0, max_dy: float = 5.0, below_dy: float = 18.0,
         below_dx: float = 90.0, confidence: float = 0.9, label_name: str = "") -> Hit | None:
    """First value accepted by ``parse`` next to a label matching ``label_pattern``."""
    regex = re.compile(label_pattern, re.I)
    for page in parsed["pages"]:
        if pages and page["page_number"] not in pages:
            continue
        lines = _lines(page)
        for line in lines:
            match = regex.search(line["text"])
            if not match:
                continue
            if inline:  # value printed in the same OCR line, after the label
                rest = line["text"][match.end():].strip(" :-")
                value = parse(rest) if rest else None
                if value is STOP:
                    continue
                if value is not None:
                    return Hit(value, page["page_number"], line["text"], confidence, label_name or match.group(0))
            for other in _neighbours(lines, line, max_dx=max_dx, max_dy=max_dy, below_dy=below_dy,
                                     below_dx=below_dx, below=below):
                value = parse(other["text"].strip())
                if value is STOP:
                    break
                if value is not None:
                    return Hit(value, page["page_number"], f"{line['text']} {other['text']}", confidence,
                               label_name or match.group(0))
    return None


# ----------------------------------------------------------------- parsers --

def p_money(text: str) -> Decimal | None:
    value = _money(text)
    return value if value is not None and value > 0 else None


def p_cc(text: str) -> int | None:
    match = re.search(r"\b([0-9]{3,4})\s*(?:cc)?\b", text, re.I)
    if match and 600 <= int(match.group(1)) <= 7000:
        return int(match.group(1))
    return None


def p_year(text: str) -> int | None:
    if re.search(r"\b0001\b|not\s*(?:provided|available)|^na$", text, re.I):
        return STOP  # e.g. Go Digit prints 0001-01-01 when the manufacture year is unknown
    match = YEAR.search(text)
    return int(match.group(1)) if match else None


def p_fuel(text: str) -> str | None:
    words = re.findall(r"[a-z]+", text.casefold())
    if len(words) > 4:
        return None
    for word in words:
        if word in FUELS:
            return FUELS[word]
    return None


def p_registration(text: str) -> str | None:
    match = REG_MARK.search(text.upper())
    if not match:
        return None
    return "".join(match.groups())


def p_text(text: str) -> str | None:
    cleaned = text.strip(" :/-")
    if len(cleaned) < 2 or re.fullmatch(r"[\d\s.,:/-]+", cleaned):
        return None
    return cleaned


def p_percent(text: str) -> Decimal | None:
    match = re.search(r"([0-9]{1,2}(?:\.[0-9]+)?)\s*%", text)
    return Decimal(match.group(1)) if match else None


def p_date(text: str) -> str | None:
    """Return ISO date from '29 Mar, 2026', '23-Dec-2025', '25-Mar-2026 00:00:01' or '01/04/2026'."""
    m = re.search(r"\b([0-3]?\d)[\s-]*([A-Za-z]{3})[a-z]*[\s,.-]*((?:19|20)\d\d)\b", text)
    if m and m.group(2).casefold()[:3] in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).casefold()[:3]]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b([0-3]?\d)[/.-]([01]?\d)[/.-]((?:19|20)\d\d)\b", text)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def _split_make(text: str) -> tuple[str | None, str | None]:
    upper = re.sub(r"\s+", " ", text.upper().replace("/", " / ")).strip(" /")
    for make in KNOWN_MAKES:
        if upper.startswith(make):
            model = upper[len(make):].strip(" /-")
            return make.title() if make not in {"MG", "BMW", "BYD", "KIA"} else make, model or None
    return None, None


LABEL_WORDS = re.compile(r"chassis|engine|cubic|capacity|year|fuel|registration|seating|policy|period|"
                         r"rto|invoice|from|to\b|premium|variant|make|model", re.I)


def p_model(text: str) -> str | None:
    cleaned = text.strip(" :/-")
    if (len(cleaned) < 2 or LABEL_WORDS.match(cleaned) or re.search(r"variant|sub-?type", cleaned, re.I)
            or re.fullmatch(r"[\d\s.,:/-]+", cleaned)):
        return None
    if len(cleaned) > 17 and re.fullmatch(r"[A-Z0-9]+", cleaned):
        return None  # chassis / engine numbers
    return re.sub(r"\s*/\s*$", "", cleaned)


def p_make_model(text: str):
    make, model = _split_make(text)
    return (make, model) if make else None


# ------------------------------------------------------------------- rules --

FIELD_RULES: list[tuple[str, str, Callable[[str], Any], dict[str, Any]]] = [
    # (fact name, label regex, parser, options)
    ("od_premium", r"net\s*own\s*damage\s*premium|total\s*own\s*damage\s*premium|total\s*od\s*premium", p_money, {}),
    ("tp_premium", r"net\s*liability\s*premium|total\s*liability\s*premium|net\s*tp\s*premium|total\s*tp\s*premium", p_money, {}),
    ("net_premium", r"^net\s*premium|total\s*package\s*premium|total\s*premium\s*\(?excl|premium\s*before\s*(?:gst|tax)",
     p_money, {"below": True}),
    ("engine_cc", r"cubic\s*capacity|cc\s*/\s*(?:hp|kw)|engine\s*capacity|^cc\b", p_cc, {}),
    ("manufacture_year", r"year\s*of\s*manufacture|mfg\.?\s*(?:month\s*&?\s*)?year|year\s*of\s*mfg|manufacturing\s*year", p_year, {}),
    ("registration_year", r"year\s*of\s*regn|date\s*of\s*registration|registration\s*date", p_year, {}),
    ("fuel", r"fuel\s*type|^fuel\b", p_fuel, {}),
    ("registration_number", r"registration\s*no|regn\.?\s*no|registration\s*number|vehicle\s*no", p_registration, {}),
    ("ncb_percent", r"no\s*claim\s*bonus|for\s*ncb|ncb\s*%|ncb\s*\(", p_percent, {"inline": True}),
]

MAKE_MODEL_LABELS = r"make\s*/\s*model|^make\b|vehicle\s*make"
MODEL_LABELS = r"model\s*/\s*vehicle\s*variant(?:\s*\(sub-?type\))?|^vehicle\s*model|^model\b"
PREVIOUS_INSURER = re.compile(r"(?:previous\s*insurer\s*[:\-]?\s*|\d{4}\s*of\s*)([A-Z][A-Z&.\s]*?(?:INSURANCE|ASSURANCE)[A-Z.\s]*)",
                              re.I)
START_LABELS = r"\bfrom\b|valid\s*from|period\s*of\s*(?:insurance|policy)|policy\s*start"


def extract(parsed: dict[str, Any]) -> dict[str, Hit]:
    hits: dict[str, Hit] = {}
    for name, label, parser, options in FIELD_RULES:
        hit = find(parsed, label, parser, label_name=name, **options)
        if hit:
            hits[name] = hit
    make_hit = find(parsed, MAKE_MODEL_LABELS, p_make_model, label_name="make/model")
    if make_hit:
        hits["make_model"] = make_hit
    model_hit = find(parsed, MODEL_LABELS, p_model, label_name="model", below=False)
    if model_hit:
        hits["model"] = model_hit
    start = find(parsed, START_LABELS, p_date, label_name="policy start", max_dx=260, max_dy=8,
                 below_dy=32, below_dx=60)
    if start:
        hits["policy_start_date"] = start
    previous = _previous_insurer(parsed)
    if previous:
        hits["previous_insurer"] = previous
    return hits


def _previous_insurer(parsed) -> Hit | None:
    """Previous insurer from a previous-policy line, e.g. '29/03/2025to28/03/2026ofTATAAIGGENERALINSURANCECO.LTD.'"""
    from .identification import identify_insurer

    for page in parsed["pages"]:
        for line in _lines(page):
            text = line["text"]
            if not (re.search(r"previous", text, re.I) or re.search(r"\d{4}\s*of\s*[A-Z]", text)):
                continue
            match = PREVIOUS_INSURER.search(text)
            if match:
                name = re.sub(r"\s+", " ", match.group(1)).strip(" .")
                key, _issue = identify_insurer(name)
                if key:
                    return Hit(INSURER_NAMES.get(key, name), page["page_number"], text, 0.85, "Previous insurer")
    return None


def apply_insurer_rules(parsed: dict[str, Any], facts) -> None:
    """Fill facts the text parser missed (or found conflicting) from layout-aware rules."""
    from .document_pipeline import _fact  # local import to avoid a cycle

    hits = extract(parsed)
    for name, hit in hits.items():
        if name == "make_model":
            make, model = hit.value
            for field, value in (("make", make), ("model", model)):
                if value and (getattr(facts, field) is None or field in facts.conflicts):
                    facts.conflicts.pop(field, None)
                    setattr(facts, field, _fact(parsed, hit.page, hit.text, hit.confidence, value, "Make / Model"))
            if make and (facts.make_model is None or "make_model" in facts.conflicts):
                combined = f"{make} {model or ''}".strip()
                facts.make_model = _fact(parsed, hit.page, hit.text, hit.confidence, combined, "Make / Model")
            continue
        if name == "model":
            if facts.model is None or "model" in facts.conflicts:
                facts.conflicts.pop("model", None)
                facts.model = _fact(parsed, hit.page, hit.text, hit.confidence, hit.value, "Model")
            continue
        if not hasattr(facts, name):
            continue
        if getattr(facts, name) is not None and name not in facts.conflicts:
            continue
        facts.conflicts.pop(name, None)
        setattr(facts, name, _fact(parsed, hit.page, hit.text, hit.confidence, hit.value, hit.label))
    if facts.make is not None:
        combined = f"{facts.make.value} {facts.model.value if facts.model else ''}".strip()
        if facts.make_model is None or str(facts.make_model.value) != combined:
            facts.make_model = _fact(parsed, facts.make.page, facts.make.text, facts.make.confidence, combined,
                                     "Make / Model")
    policy_title = str(facts.policy_type.value if facts.policy_type else "").casefold()
    standalone_tp = "standalone tp" in policy_title or "liability only" in policy_title
    if standalone_tp and facts.tp_premium is None and facts.net_premium is not None:
        # On a standalone-TP (liability only) policy the whole net premium is liability premium.
        source = facts.net_premium
        facts.tp_premium = _fact(parsed, source.page, source.text, source.confidence, source.value,
                                 "Net premium (liability-only policy)")
    if facts.ncb_state is None and facts.ncb_percent is not None:
        state = "NCB" if Decimal(str(facts.ncb_percent.value)) > 0 else "Non-NCB"
        source = facts.ncb_percent
        facts.ncb_state = _fact(parsed, source.page, source.text, source.confidence, state, "NCB (from NCB %)")
    resolved = {name for name, fact in vars(facts).items() if fact is not None and not isinstance(fact, (dict, list))}
    facts.missing_or_uncertain = [note for note in facts.missing_or_uncertain
                                  if note.split(" ")[0] not in resolved]
