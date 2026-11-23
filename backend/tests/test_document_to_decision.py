from pathlib import Path
from decimal import Decimal

import pymupdf
import pytest

from app.rating_engine.document_pipeline import document_to_decision, result_dict
from app.rating_engine.document_pipeline import (
    ExtractedFact, StructuredPolicyFacts, extract_structured_facts, normalize_policy_input,
)
from app.rating_engine.models import SourceRef

ROOT = Path(__file__).resolve().parents[2]
POLICIES = ROOT / "sample-policies"
CARDS = ROOT / "backend" / "rate_cards"


# Every value below was read by eye from the scanned sample PDFs (the policy
# schedule pages). Extraction is AI-free: local OCR plus layout-aware rules.
# A value the PDF does not print (HDFC/Reliance fuel, Tata segment/business
# type, Go Digit manufacture year printed as 0001-01-01) must stay missing.
EXPECTED_FACTS = {
    "pvt-car-comprehensive-hdfc-ergo.pdf": {
        "insurer": "hdfc-ergo", "policy_type": "Private Car Package", "fuel": None,
        "previous_insurer": "Tata AIG General Insurance Co. Ltd.", "engine_cc": "1493",
        "manufacture_year": "2023", "rto": "GURGAON", "state": "Haryana",
        "registration_number": "HR-26-FB-8239", "make_model": "Mahindra BOLERO NEO-N10 (R)",
        "policy_start_date": "2026-03-29", "od_premium": "8053", "tp_premium": "3816",
        "net_premium": "11869", "ncb_percent": "35", "ncb_state": "NCB"},
    "pvt-car-comprehensive-reliance.pdf": {
        "insurer": "reliance-indusind", "policy_type": "Private Car Package", "fuel": None,
        "engine_cc": "999", "manufacture_year": "2020", "registration_year": "2020",
        "state": "Uttar Pradesh", "registration_number": "UP16CS5830", "make_model": "Renault KWID1.0 RXT O",
        "policy_start_date": "2025-12-23", "od_premium": "4714", "tp_premium": "2519",
        "net_premium": "7233", "ncb_percent": "25", "ncb_state": "NCB"},
    "pvt-car-satp-go-digit.pdf": {
        "insurer": "godigit", "policy_type": "Standalone TP", "fuel": "Petrol",
        "previous_insurer": "Go Digit General Insurance Ltd.", "engine_cc": "1086", "manufacture_year": None,
        "registration_year": "2019", "rto": "Kanpur Nagar,UTTAR PRADESH", "state": "Uttar Pradesh",
        "registration_number": "UP78FZ1372", "make_model": "HYUNDAI SANTRO NEW/1.1MT CORPORATE",
        "policy_start_date": "2026-03-25", "tp_premium": "3466", "net_premium": "3466"},
    "pvt-car-satp-tata-aig.pdf": {
        "insurer": "tata-aig", "policy_type": "Standalone TP", "fuel": "CNG", "engine_cc": "998",
        "manufacture_year": "2011", "registration_year": "2011", "rto": "DELHI", "state": "Delhi",
        "registration_number": "DL9CAB2893", "make_model": "Maruti ZENESTILO",
        "policy_start_date": "2026-04-01", "tp_premium": "2154", "net_premium": "2154"},
}

# Inputs the PDF does not print are supplied by the reviewer; the result must then
# be the rate-card commission, checked by hand.
REVIEW = {
    "pvt-car-comprehensive-hdfc-ergo.pdf": ({"fuel": "Diesel"}, "1207.95"),        # 8053 x 15%
    "pvt-car-comprehensive-reliance.pdf": ({"fuel": "Petrol"}, "353.55"),          # 4714 x 7.5%
    "pvt-car-satp-go-digit.pdf": ({}, "1022.47"),                                  # 3466 x 29.5%
    "pvt-car-satp-tata-aig.pdf": ({"business_type": "Rollover", "vehicle_segment": "Compact"}, "818.52"),
}


@pytest.fixture(scope="module")
def sample_results():
    return {name: result_dict(document_to_decision(POLICIES / name, rate_card_root=CARDS))
            for name in EXPECTED_FACTS}


@pytest.mark.parametrize("filename", sorted(EXPECTED_FACTS))
def test_rule_extraction_matches_every_printed_value(sample_results, filename):
    facts = sample_results[filename]["facts"]
    wrong = {name: ((facts.get(name) or {}).get("value"), expected)
             for name, expected in EXPECTED_FACTS[filename].items()
             if (facts.get(name) or {}).get("value") != expected}
    assert not wrong, f"extracted != printed: {wrong}"
    for name, fact in facts.items():
        if fact:  # every extracted value cites the page it was read from
            assert fact["page"] >= 1 and fact["text"], name


@pytest.mark.parametrize("filename", sorted(REVIEW))
def test_reviewed_commission_matches_rate_card(sample_results, filename):
    from app.rating_engine.review import rerate

    overrides, expected_total = REVIEW[filename]
    reviewed = rerate(sample_results[filename], overrides, CARDS)
    assert reviewed["decisions"]["overall"] == "resolved"
    assert reviewed["totals"]["commission_total"] == expected_total
    assert reviewed["assessment_status"] == "complete"


def _image_only_pdf(path, pages=1):
    source = pymupdf.open()
    source.new_page(width=300, height=400).insert_text((40, 60), "scanned", fontsize=14)
    png = source[0].get_pixmap().tobytes("png")
    source.close()
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=300, height=400)
        page.insert_image(page.rect, stream=png)
    doc.save(path)
    doc.close()
    return path


def test_low_confidence_fact_is_flagged_by_normalization():
    facts = StructuredPolicyFacts(insurer=ExtractedFact(
        "godigit", 1, 0.40, "uncertain OCR", SourceRef("scan.pdf", "a" * 64, page=1)))
    normalized = normalize_policy_input(facts)
    assert normalized.insurer is None


def parsed_text_page(text, page_number=1, sha="b" * 64, ocr_lines=None):
    return {"document_name": "synthetic-layout.pdf", "sha256": sha, "page_count": page_number,
            "ocr_pages_limited": False, "pages": [{"page_number": page_number, "text": text,
            "ocr_lines": ocr_lines or [], "ocr_used": bool(ocr_lines), "tables": []}]}


def test_current_issuer_is_header_context_and_previous_insurer_is_independent():
    from app.rating_engine.document_pipeline import extract_structured_facts
    text = "HDFC ERGO General Insurance Company Limited\nPrivate Car Package Policy\nPrevious Insurer: Reliance General Insurance\nReliance General Insurance was mentioned again.\nReliance General Insurance was mentioned a third time."
    lines = [
        {"text": "HDFC ERGO General Insurance Company Limited", "confidence": .99, "x": 20, "y": 30},
        {"text": "Private Car Package Policy", "confidence": .99, "x": 20, "y": 70},
        {"text": "Previous Insurer: Reliance General Insurance", "confidence": .99, "x": 20, "y": 220},
        {"text": "Reliance General Insurance was mentioned again.", "confidence": .99, "x": 20, "y": 300},
    ]
    facts = extract_structured_facts(parsed_text_page(text, ocr_lines=lines))
    assert facts.insurer and facts.insurer.value == "hdfc-ergo"
    assert facts.previous_insurer and "Reliance" in facts.previous_insurer.value
    assert "insurer" not in facts.conflicts


def test_multiple_issuer_header_candidates_are_a_conflict():
    text = "HDFC ERGO General Insurance\nReliance General Insurance\nPrivate Car Package Policy"
    lines = [
        {"text": "HDFC ERGO General Insurance", "confidence": .99, "x": 10, "y": 30},
        {"text": "Reliance General Insurance", "confidence": .99, "x": 10, "y": 55},
        {"text": "Private Car Package Policy", "confidence": .99, "x": 10, "y": 90},
    ]
    facts = extract_structured_facts(parsed_text_page(text, ocr_lines=lines))
    assert facts.insurer is None
    assert {fact.value for fact in facts.conflicts["insurer"]} == {"hdfc-ergo", "reliance-indusind"}


def test_package_with_third_party_section_stays_package():
    parsed = parsed_text_page(
        "HDFC ERGO General Insurance Company Limited\nPrivate Car Package Policy\n"
        "Section II: Third Party Liability. The insurer covers legal liability to third parties.")
    facts = extract_structured_facts(parsed)
    assert facts.policy_type and facts.policy_type.value == "Private Car Package"
    assert "policy_type" not in facts.conflicts


def test_explicit_satp_policy_title_is_classified_as_satp():
    parsed = parsed_text_page("Tata AIG General Insurance Company Limited\nAuto Secure - Liability Only Policy")
    facts = extract_structured_facts(parsed)
    assert facts.policy_type and facts.policy_type.value == "Standalone TP"


def test_conflicting_fuel_and_premium_candidates_keep_page_provenance():
    lines = [
        {"text": "Fuel Type: Petrol", "confidence": .99, "x": 10, "y": 100},
        {"text": "Fuel Type: Diesel", "confidence": .98, "x": 10, "y": 120},
        {"text": "Net Own Damage Premium: 5000.00", "confidence": .99, "x": 10, "y": 160},
        {"text": "Total Own Damage Premium: 7000.00", "confidence": .99, "x": 10, "y": 180},
    ]
    lines.append({"text": "Insured Declared Value: 900000", "confidence": .99, "x": 10, "y": 200})
    parsed = parsed_text_page("\n".join(line["text"] for line in lines), ocr_lines=lines)
    facts = extract_structured_facts(parsed)
    assert facts.fuel is None and {f.value for f in facts.conflicts["fuel"]} == {"Petrol", "Diesel"}
    assert facts.od_premium is None and {f.value for f in facts.conflicts["od_premium"]} == {Decimal("5000.00"), Decimal("7000.00")}
    assert {f.page for f in facts.conflicts["fuel"] + facts.conflicts["od_premium"]} == {1}


def test_ocr_low_confidence_fuel_candidate_is_retained_but_not_normalized():
    line = {"text": "Fuel Type: Petrol", "confidence": .31, "x": 10, "y": 100}
    facts = extract_structured_facts(parsed_text_page(line["text"], ocr_lines=[line]))
    assert facts.fuel is None
    assert facts.low_confidence["fuel"][0].value == "Petrol"
    assert facts.low_confidence["fuel"][0].page == 1
    assert normalize_policy_input(facts).fuel is None


def test_unfamiliar_layout_fails_closed_without_a_rate(tmp_path):
    path = tmp_path / "unfamiliar.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 40), "Example Motor Cover\nRoad protection schedule")
    doc.save(path)
    doc.close()
    result = document_to_decision(path, rate_card_root=CARDS)
    assert result.facts.insurer is None
    assert result.facts.policy_type is None
    assert result.decision.od.rate_percent is None
    assert result.decision.tp.rate_percent is None


