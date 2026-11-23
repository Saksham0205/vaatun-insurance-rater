"""Gemini document extraction with independent evidence validation."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger("vaatun.gemini")


class Candidate(BaseModel):
    raw_value: str | int | float | None = None
    normalized_value: str | int | float | None = None
    page: int | None = None
    evidence: str | None = None
    source_label: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    extraction_method: str = "gemini_pdf"


class GeminiPolicyExtraction(BaseModel):
    fields: dict[str, list[Candidate]] = Field(default_factory=dict)
    insurer_profile: str | None = None


FIELD_NAMES = (
    "insurer", "previous_insurer", "business_type", "policy_type", "policy_number", "proposal_number",
    "make", "model", "registration_number", "rto", "state", "engine_cc", "fuel", "manufacture_year",
    "basic_od_premium", "ncb_discount_amount", "od_premium", "basic_tp_premium", "other_tp_charges",
    "tp_premium", "total_package_premium", "integrated_tax", "total_premium", "idv", "ncb_percent",
    "ncb_eligibility", "ncb_state", "total_addon_premium"
)

PROMPT = """Extract Indian motor-policy fields from this PDF. Return structured candidates only.
Each candidate must cite page, exact visual evidence, source label, raw and normalized values, and confidence.
Use null/missing candidates rather than guessing. Keep current insurer distinct from previous insurer.
Never mix Basic OD, NCB deduction, add-ons, Net OD, Basic TP, other TP, Net TP, package premium, tax, or total-with-tax.
Fuel is null unless explicitly printed. For HDFC inspect Vehicle Details and Premium Details; for Digit inspect schedule/standalone TP; for Reliance inspect premium and previous insurer; for Tata AIG inspect vehicle schedule/coverage.
Extract every policy fact needed to select a commission rule when it is printed: insurer, prior insurer,
business type, product, fuel, engine capacity, RTO, state, OD/TP premiums, and NCB state. `business_type`
must be `new` or `renewal` only when the schedule explicitly supports it. `ncb_state` must be `NCB`
only where a positive NCB is explicitly stated, `Non-NCB` only where zero/no NCB is explicitly stated,
otherwise null. Do not infer fuel, zone, RTO-to-zone mapping, or a premium slab when it is absent.

Return ONLY a valid JSON object matching this structure:
{
  "fields": {
    "field_name": [
      {
        "raw_value": "raw extracted string or number",
        "normalized_value": "cleaned string or numeric value",
        "page": 1,
        "evidence": "exact text from page",
        "source_label": "table or section label",
        "confidence": 0.95
      }
    ]
  },
  "insurer_profile": "optional notes"
}
Available field_name keys:
"insurer", "previous_insurer", "business_type", "policy_type", "policy_number", "proposal_number",
"make", "model", "registration_number", "rto", "state", "engine_cc", "fuel", "manufacture_year",
"basic_od_premium", "ncb_discount_amount", "od_premium", "basic_tp_premium", "other_tp_charges",
"tp_premium", "total_package_premium", "integrated_tax", "total_premium", "idv", "ncb_percent",
"ncb_eligibility", "ncb_state", "total_addon_premium"
"""


def _clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


def _compact(s: str | int | float | None) -> str:
    """Make OCR's lost spaces/punctuation irrelevant without accepting new words."""
    return re.sub(r"[^a-z0-9]+", "", str(s or "").casefold())


def _value_is_cited(candidate: Candidate) -> bool:
    """Reject a value that Gemini did not actually quote from its evidence excerpt."""
    value = candidate.raw_value if candidate.raw_value is not None else candidate.normalized_value
    evidence = candidate.evidence or ""
    if value is None or not evidence.strip():
        return False
    try:
        # Monetary values may be quoted as 8053 while normalized as 8053.0.
        value_number = float(str(value).replace(",", ""))
        numeric_forms = {
            str(value_number),
            format(value_number, "f").rstrip("0").rstrip("."),
        }
        return any(_compact(item) in _compact(evidence) for item in numeric_forms if item)
    except (TypeError, ValueError):
        compact_value = _compact(value)
        return bool(compact_value) and compact_value in _compact(evidence)


def _evidence_matches(candidate: Candidate, page_text: str, field_name: str | None = None) -> bool:
    evidence = candidate.evidence or ""
    if not candidate.page or not evidence.strip() or not page_text.strip():
        return False
    # OCR preserves words but commonly removes spaces within titles and table cells.
    # Compare a punctuation/space-insensitive form after first enforcing that the
    # returned value itself is present in the cited evidence.
    compact_page = _compact(page_text)
    compact_evidence = _compact(evidence)
    # OCR table reading order may put a label and its same-row value far apart
    # in the emitted text. Accept that layout loss only when every meaningful
    # evidence token is independently visible on the cited page.
    evidence_tokens = [token for token in re.findall(r"[a-z0-9]+", evidence.casefold()) if len(token) > 1]
    evidence_on_page = compact_evidence in compact_page or (
        bool(evidence_tokens) and all(_compact(token) in compact_page for token in evidence_tokens)
    )
    if not evidence_on_page:
        return False
    if field_name == "ncb_state":
        # NCB/Non-NCB is a normalized rating category, not necessarily literal
        # document text. Its evidence must nevertheless name the NCB concept and
        # contain a percentage that supports the selected category.
        category_evidence = f"{evidence} {candidate.source_label or ''}"
        percentages = [float(value) for value in re.findall(r"(\d{1,2}(?:\.\d+)?)\s*%", category_evidence)]
        normalized = _clean(str(candidate.normalized_value))
        return (normalized == "ncb" and any(value > 0 for value in percentages)
                and bool(re.search(r"ncb|no\s*claim\s*bonus", category_evidence, re.I))) or (
                normalized == "non-ncb" and any(value == 0 for value in percentages)
                and bool(re.search(r"ncb|no\s*claim\s*bonus", category_evidence, re.I)))
    return _value_is_cited(candidate)


def extract_pdf(path: str | Path, page_text: dict[int, str]) -> tuple[GeminiPolicyExtraction | None, dict[str, Any]]:
    if not settings.gemini_api_key or not settings.gemini_extraction_enabled:
        logger.warning("Gemini extraction skipped: api_key configured=%s, enabled=%s",
                       bool(settings.gemini_api_key), settings.gemini_extraction_enabled)
        return None, {"status": "disabled", "engine": "gemini"}

    pdf = Path(path)
    file_bytes = pdf.read_bytes()
    logger.info("Starting Gemini PDF extraction: model=%s, file=%s (%d bytes)",
                settings.gemini_model, pdf.name, len(file_bytes))

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        # Note: We omit response_schema because the google-genai SDK currently rejects schemas
        # with Union types (AnyOf) or default values. We enforce JSON via response_mime_type and prompt.
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[types.Part.from_bytes(data=file_bytes, mime_type="application/pdf"), PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        logger.info("Gemini API call succeeded (%d chars in response)", len(response.text or ""))
        data = json.loads(response.text)
        extraction = GeminiPolicyExtraction.model_validate(data)
        logger.info("Gemini raw extraction parsed: found %d candidate fields", len(extraction.fields))
    except Exception as exc:
        logger.exception("Gemini PDF extraction failed for %s: %s", pdf.name, exc)
        return None, {"status": "failed", "engine": "gemini", "model": settings.gemini_model,
                      "error_type": type(exc).__name__, "error_detail": str(exc)}

    verified: dict[str, list[Candidate]] = {}
    rejected = 0
    for name, candidates in extraction.fields.items():
        if name not in FIELD_NAMES:
            continue
        for candidate in candidates:
            text = page_text.get(candidate.page or -1, "")
            if _evidence_matches(candidate, text, name):
                verified.setdefault(name, []).append(candidate)
                logger.info("  [VERIFIED] %s: %r (page %s)", name, candidate.normalized_value, candidate.page)
            else:
                rejected += 1
                logger.warning("  [REJECTED] %s: %r (page %s, evidence %r not matched in page text)",
                               name, candidate.normalized_value, candidate.page, candidate.evidence)

    extraction.fields = verified
    logger.info("Gemini verification finished for %s: %d validated candidates, %d rejected",
                pdf.name, sum(map(len, verified.values())), rejected)
    return extraction, {
        "status": "completed", "engine": "gemini", "model": settings.gemini_model,
        "validated_candidates": sum(map(len, verified.values())), "unverified_candidates": rejected
    }
