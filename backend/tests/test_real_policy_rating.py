"""Regression coverage using the restored policy PDFs and supplied rate cards."""
from pathlib import Path
from decimal import Decimal

from app.rating_engine import rate_policy
from app.rating_engine.catalog import sha256_file
from app.rating_engine.models import PolicyInput, SourceRef
from app.rating_engine.parsers import parse_pdf, parse_workbook

ROOT = Path(__file__).resolve().parents[2]
POLICIES = ROOT / "sample-policies"
CARDS = ROOT / "backend" / "rate_cards"


def policy_ref(filename, page, role):
    path = POLICIES / filename
    return SourceRef(filename, sha256_file(path), page=page, role=role)


def test_actual_policy_pdfs_parse_and_produce_od_tp_decisions():
    cases = [
        ("pvt-car-comprehensive-hdfc-ergo.pdf", PolicyInput(
            insurer="HDFC ERGO General Insurance Company Limited", previous_insurer="Tata AIG",
            policy_type="Private Car Comprehensive Package", fuel=None, engine_cc=1493,
            rto="HR-26 Gurgaon", zone="Zone 2", od_premium_band="<10k",
            ncb_state=None, source_evidence={
                "zone": [policy_ref("pvt-car-comprehensive-hdfc-ergo.pdf", 2, "zone mapping")],
                "od_premium_band": [policy_ref("pvt-car-comprehensive-hdfc-ergo.pdf", 1, "OD premium")],
                "ncb_state": [
                    policy_ref("pvt-car-comprehensive-hdfc-ergo.pdf", 1, "NCB section: Valid 25%"),
                    policy_ref("pvt-car-comprehensive-hdfc-ergo.pdf", 1, "premium section: Less NCB 35%"),
                ],
            })),
        ("pvt-car-satp-go-digit.pdf", PolicyInput(
            insurer="Go Digit General Insurance Ltd.", previous_insurer="Go Digit General Insurance Limited",
            policy_type="Private Car Standalone TP SATP Liability Only", fuel="Petrol", engine_cc=1086,
            vehicle_age_years=7, rto="Kanpur Nagar, Uttar Pradesh",
            source_evidence={"fuel": [policy_ref("pvt-car-satp-go-digit.pdf", 1, "fuel")]})),
        ("pvt-car-comprehensive-reliance.pdf", PolicyInput(
            insurer="Reliance General Insurance Company Limited", policy_type="Private Car Package",
            fuel=None, engine_cc=999, rto="UP Noida", ncb_state="NCB",
            od_premium=Decimal("4714"),
            source_evidence={"rto": [policy_ref("pvt-car-comprehensive-reliance.pdf", 2, "RTO")]})),
        ("pvt-car-satp-tata-aig.pdf", PolicyInput(
            insurer="Tata AIG General Insurance Company Limited", policy_type="Auto Secure Standalone TP Liability Only SATP",
            fuel="CNG", engine_cc=998, vehicle_age_years=15, rto="Delhi", zone="Zone A",
            source_evidence={"fuel": [policy_ref("pvt-car-satp-tata-aig.pdf", 4, "fuel")]})),
    ]
    expected = {
        "pvt-car-comprehensive-hdfc-ergo.pdf": ("ambiguous", "unsupported"),
        "pvt-car-satp-go-digit.pdf": ("not_applicable", "ambiguous"),
        "pvt-car-comprehensive-reliance.pdf": ("ambiguous", "ambiguous"),
        "pvt-car-satp-tata-aig.pdf": ("not_applicable", "ambiguous"),
    }
    for filename, facts in cases:
        parsed = parse_pdf(POLICIES / filename, ocr_fallback=False)
        assert parsed["sha256"] == sha256_file(POLICIES / filename)
        assert parsed["document_name"] == filename
        result = rate_policy(facts, CARDS)
        assert (result.od.status.value, result.tp.status.value) == expected[filename]
        assert result.od.rate_percent is None and result.tp.rate_percent is None
        assert result.od.status.value in {"resolved", "not_applicable", "unsupported", "ambiguous"}
        assert result.tp.status.value in {"resolved", "not_applicable", "unsupported", "ambiguous"}


def test_real_card_explicit_zero_is_distinct_from_blank():
    path = next((CARDS / "godigit").rglob("*.xlsx"))
    parsed = parse_workbook(path, {"4W SATP"})
    cells = {cell.ref.cell: cell.original_value for cell in parsed["sheets"][0]["cells"]}
    assert cells["E3"] == 0
    assert cells["E3"] is not None


def test_actual_policy_hashes_match_manifest():
    from app.rating_engine.catalog import source_audit
    audit = source_audit(ROOT)
    assert len(audit["manifest_checks"]) == 10
    assert all(item["matches"] for item in audit["manifest_checks"])
