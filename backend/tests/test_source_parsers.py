"""Parser tests against the real supplied rate-card files; these are not policy validation."""
from pathlib import Path

from app.rating_engine.catalog import source_audit
from app.rating_engine.parsers import parse_pdf, parse_workbook
from app.rating_engine.adapters.hdfc import HDFCAdapter
from app.rating_engine import rate_policy
from app.rating_engine.models import PolicyInput, SourceRef


ROOT = Path(__file__).resolve().parents[2]
RATE_CARDS = ROOT / "backend" / "rate_cards"


def test_bundle_audit_verifies_restored_fixtures_and_manifest():
    audit = source_audit(ROOT)
    assert len(audit["rate_cards"]) == 4
    assert audit["manifest_present"]
    assert not audit["missing_policy_files"]
    assert len(audit["manifest_checks"]) == 10
    assert all(item["matches"] for item in audit["manifest_checks"])


def test_excel_parser_preserves_sheet_cell_formula_and_cached_value():
    path = next((RATE_CARDS / "godigit").rglob("*.xlsx"))
    workbook = parse_workbook(path, {"4W SATP"})
    assert workbook["workbook_name"] == path.name
    assert workbook["sha256"]
    sheet = workbook["sheets"][0]
    assert sheet["name"] == "4W SATP"
    cell_a59 = next(c for c in sheet["cells"] if c.ref.cell == "A59")
    assert cell_a59.formula == "=B59&C59&D59"
    assert cell_a59.ref.sheet == "4W SATP"


def test_pdf_parser_preserves_page_table_and_raw_cells():
    path = next((RATE_CARDS / "hdfc-ergo").rglob("*.pdf"))
    parsed = parse_pdf(path)
    assert parsed["document_name"] == path.name
    assert len(parsed["pages"]) == 2
    assert parsed["pages"][0]["tables"][0]["table_number"] == 1
    assert parsed["pages"][0]["tables"][0]["rows"][4]["cells"][1]


def test_hdfc_rate_rules_parse_source_values_and_exact_pdf_references():
    rules = HDFCAdapter(RATE_CARDS).rules()
    assert len(rules) == 60
    z1 = next(r for r in rules if r.conditions == {
        "zone": "Zone 1", "product": "Package", "fuel_group": "petrol",
        "ncb_state": "any", "od_premium_band": "<10k"})
    assert str(z1.rate_percent) == "17.5"
    assert z1.source_value.ref.page == 1
    assert z1.source_value.ref.table == 1
    assert z1.source_value.ref.row == 5
    assert z1.source_value.ref.column == 2
    assert z1.source_value.original_value is not None


def test_hdfc_od_resolves_from_real_grid_with_synthetic_policy_facts_and_tp_stays_unsupported():
    policy_ref = SourceRef("synthetic-policy.pdf", page=1, role="synthetic_policy_evidence")
    policy = PolicyInput(
        insurer="HDFC ERGO", policy_type="Package", cover="Package", zone="Zone 1",
        fuel="Petrol", od_premium_band="<10k", business_type="New",
        source_evidence={"zone": [policy_ref], "fuel": [policy_ref], "od_premium_band": [policy_ref]},
    )
    result = rate_policy(policy, RATE_CARDS)
    assert result.od.status.value == "resolved"
    assert str(result.od.rate_percent) == "17.5"
    assert result.od.evidence[-1].source_file == HDFCAdapter(RATE_CARDS).path.name
    assert result.tp.status.value == "unsupported"
    assert result.status.value == "unsupported"  # OD resolves; TP is deliberately unresolved.
