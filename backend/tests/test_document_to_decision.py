from pathlib import Path
import hashlib
from decimal import Decimal

import pymupdf

from app.rating_engine.document_pipeline import document_to_decision, result_dict
from app.rating_engine.document_pipeline import (
    ExtractedFact, StructuredPolicyFacts, extract_structured_facts, normalize_policy_input,
)
from app.rating_engine.models import DecisionStatus, SourceRef

ROOT = Path(__file__).resolve().parents[2]
POLICIES = ROOT / "sample-policies"
CARDS = ROOT / "backend" / "rate_cards"


def test_all_real_sample_pdfs_run_ocr_extraction_normalization_and_rating(monkeypatch):
    from app.rating_engine import document_pipeline
    real_rate_policy = document_pipeline.rate_policy
    passed_inputs = []

    def capture_policy_input(policy_input, rate_card_root=None):
        passed_inputs.append(policy_input)
        return real_rate_policy(policy_input, rate_card_root)

    monkeypatch.setattr(document_pipeline, "rate_policy", capture_policy_input)
    expected = {
        "pvt-car-comprehensive-hdfc-ergo.pdf": ("hdfc-ergo", "ambiguous", "unsupported"),
        "pvt-car-satp-go-digit.pdf": ("godigit", "not_applicable", "ambiguous"),
        "pvt-car-comprehensive-reliance.pdf": ("reliance-indusind", "ambiguous", "ambiguous"),
        "pvt-car-satp-tata-aig.pdf": ("tata-aig", "not_applicable", "ambiguous"),
    }
    for filename, (insurer, od_status, tp_status) in expected.items():
        # Exercise all four fixtures with an explicit resource cap; the result must
        # identify any incomplete scan rather than present it as a complete assessment.
        result = document_to_decision(POLICIES / filename, rate_card_root=CARDS, max_ocr_pages=4)
        assert result.document_name == filename
        assert len(result.document_sha256) == 64
        assert result.document_sha256 == hashlib.sha256((POLICIES / filename).read_bytes()).hexdigest()
        assert result.page_count > 0
        assert result.ocr_pages  # The restored policies are scanned and OCR ran.
        assert result.facts.insurer is not None
        assert result.policy_input.insurer == insurer
        assert result.policy_input.source_evidence["insurer"][0].source_sha256 == result.document_sha256
        assert result.decision.od.status.value == od_status
        assert result.decision.tp.status.value == tp_status
        assert result.decision.od.status in set(DecisionStatus)
        assert result.decision.tp.status in set(DecisionStatus)
        assert result.decision.od.rate_percent is None
        assert result.decision.tp.rate_percent is None
        assert result.decision.od.evidence or result.decision.od.status.value == "not_applicable"
        assert result.decision.tp.evidence
        assert all(ref.source_sha256 for ref in result.decision.od.evidence + result.decision.tp.evidence)
        if "hdfc-ergo" in filename:
            assert result.facts.fuel is None
            assert result.facts.ncb_percent and result.facts.ncb_percent.value == 35
            assert result.facts.ncb_eligibility and "25" in result.facts.ncb_eligibility.value
            assert result.policy_input.fuel is None
            assert result.policy_input.ncb_state is None
            assert result.policy_input.ncb_state is None
        if result.ocr_pages_limited:
            assert result_dict(result)["assessment_status"] == "incomplete"
        elif "go-digit" in filename:
            assert result.facts.fuel and result.facts.fuel.value == "Petrol"
            assert result.facts.engine_cc and result.facts.engine_cc.value == 1086
            assert result.facts.rto and "Kanpur" in result.facts.rto.value
        elif "reliance" in filename:
            assert result.facts.engine_cc and result.facts.engine_cc.value == 999
            assert result.facts.rto and "Noida" in result.facts.rto.value
        elif "tata-aig" in filename:
            assert result.facts.fuel and result.facts.fuel.value == "CNG"
        for field_name in ("insurer", "policy_type"):
            fact = getattr(result.facts, field_name)
            assert fact and fact.page >= 1 and fact.confidence > 0
            assert fact.source.source_file == filename
        rendered = result_dict(result)
        assert rendered["decisions"]["OD"]["status"] == od_status
        assert rendered["decisions"]["TP"]["status"] == tp_status
    assert len(passed_inputs) == 4
    assert all(item.insurer for item in passed_inputs)
    assert all(item.source_evidence.get("insurer") for item in passed_inputs)

def test_unseen_scanned_pdf_uses_ocr_pipeline_without_sample_specific_facts(tmp_path):
    image_only = tmp_path / "unseen-scanned-policy.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 100), "Go Digit General Insurance Ltd.", fontsize=18)
    page.insert_text((60, 150), "Digit Private Car Liability Only Policy", fontsize=16)
    page.insert_text((60, 210), "Fuel Type: Petrol", fontsize=14)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    doc.close()
    image_doc = pymupdf.open()
    page = image_doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    image_doc.save(image_only)
    image_doc.close()

    result = document_to_decision(image_only, rate_card_root=CARDS)
    assert result.document_name == image_only.name
    assert result.ocr_pages == [1]
    assert result.facts.insurer and result.facts.insurer.value == "godigit"
    assert result.facts.policy_type and result.facts.policy_type.value == "Standalone TP"
    assert result.facts.fuel and result.facts.fuel.value == "Petrol"
    assert result.policy_input.source_evidence["fuel"][0].source_file == image_only.name
    assert result.decision.od.status.value == "not_applicable"
    assert result.decision.tp.status.value == "ambiguous"
    assert result.decision.tp.rate_percent is None


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


def test_late_page_fuel_is_extracted_with_default_full_coverage(tmp_path, monkeypatch):
    import app.rating_engine.parsers.pdf as pdf_parser
    monkeypatch.delenv("VAATUN_MAX_OCR_PAGES", raising=False)
    calls = {"count": 0}

    def fake_ocr(_image):
        calls["count"] += 1
        page = calls["count"]
        texts = {
            1: ["HDFC ERGO General Insurance Company Limited", "Private Car Package Policy"],
            5: ["Fuel Type: Diesel"],
        }.get(page, [])
        lines = []
        for i, text in enumerate(texts):
            y = 60 + i * 40
            lines.append(([[20, y], [300, y], [300, y + 20], [20, y + 20]], text, .99))
        return lines, None

    monkeypatch.setattr(pdf_parser, "_get_ocr_engine", lambda: fake_ocr)
    path = tmp_path / "late-fuel.pdf"
    source = pymupdf.open()
    source.new_page(width=300, height=400)
    pix = source[0].get_pixmap()
    source.close()
    doc = pymupdf.open()
    for _ in range(5):
        page = doc.new_page(width=300, height=400)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
    doc.save(path)
    doc.close()
    result = document_to_decision(path, rate_card_root=CARDS)
    assert not result.ocr_pages_limited
    assert calls["count"] == 5
    assert result.ocr_pages == [1, 2, 3, 4, 5]
    assert result.facts.fuel and result.facts.fuel.value == "Diesel"
    assert result.facts.fuel.page == 5
    assert result_dict(result)["assessment_status"] == "complete"


def test_ocr_limit_marks_assessment_incomplete(tmp_path, monkeypatch):
    import app.rating_engine.parsers.pdf as pdf_parser
    monkeypatch.setattr(pdf_parser, "_get_ocr_engine", lambda: (lambda image: ([], None)))
    monkeypatch.setenv("VAATUN_MAX_OCR_PAGES", "1")
    path = tmp_path / "limited-scan.pdf"
    doc = pymupdf.open()
    blank = doc.new_page(width=300, height=400)
    pix = blank.get_pixmap()
    doc.close()
    scanned = pymupdf.open()
    for _ in range(2):
        page = scanned.new_page(width=300, height=400)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
    scanned.save(path)
    scanned.close()
    result = document_to_decision(path, rate_card_root=CARDS)
    rendered = result_dict(result)
    assert result.ocr_pages_limited
    assert rendered["assessment_status"] == "incomplete"


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
