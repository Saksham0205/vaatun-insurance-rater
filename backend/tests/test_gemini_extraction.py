from pathlib import Path

from app.config import settings
from app.rating_engine.gemini_extraction import Candidate, _evidence_matches, extract_pdf


def test_gemini_is_disabled_without_explicit_enablement(tmp_path, monkeypatch):
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(settings, "gemini_extraction_enabled", False)
    extraction, metadata = extract_pdf(pdf, {1: "Vehicle Details"})
    assert extraction is None
    assert metadata == {"status": "disabled", "engine": "gemini"}


def test_evidence_validation_accepts_ocr_layout_loss_but_requires_the_value():
    page = "PRIVATECARCOMPREHENSIVEPOLICY\nBasic Own Damage\n2433\nTotalPremium\n14005"
    policy_type = Candidate(raw_value="COMPREHENSIVE", normalized_value="Private Car Package",
                            page=1, evidence="PRIVATE CAR COMPREHENSIVE POLICY")
    premium = Candidate(raw_value=2433, normalized_value=2433.0, page=1,
                        evidence="Basic Own Damage 2433")
    invented = Candidate(raw_value=1, normalized_value=1, page=1, evidence="NCB Valid 25%")
    ncb_state = Candidate(raw_value="25%", normalized_value="NCB", page=1,
                          evidence="25%", source_label="NCB")

    assert _evidence_matches(policy_type, page)
    assert _evidence_matches(premium, page)
    assert not _evidence_matches(invented, page)
    assert _evidence_matches(ncb_state, "NCB Valid 25%", "ncb_state")
