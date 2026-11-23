from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from pathlib import Path

from ..exceptions import exception_decision
from ..models import (Component, ComponentDecision, DecisionStatus, NormalizedRateRule,
                      PolicyInput, SourceRef, SourceValue)
from ..parsers.pdf import parse_pdf
from ..premium import hdfc_band_from_premium


HDFC_CARD_VERSION = "effective 2025-02-01"
HDFC_FILENAME = "Pvt Car New Grid Eff 1st Feb'25 (HDFC ergo) 1.pdf"
SLAB_ROWS = {"<10k": 5, ">10-50k": 6, ">50k-1L": 7, ">1L-2L": 8, ">2L": 9}

# Direct transcription of the PDF's geography tables (page 1, table 3; page
# 2, table 1).  A state with city/rest-of-state exceptions is deliberately not
# listed here: its city must be supplied exactly rather than guessed from RTO.
HDFC_STATE_ZONES = {
    "andhra pradesh": ("Zone 1", 1), "arunachal pradesh": ("Zone 1", 1),
    "bihar": ("Zone 1", 1), "chhattisgarh": ("Zone 2", 1),
    "goa": ("Zone 1", 1), "haryana": ("Zone 2", 2),
    "himachal pradesh": ("Zone 2", 2), "jharkhand": ("Zone 1", 1),
    "kerala": ("Zone 2", 1), "madhya pradesh": ("Zone 2", 2),
    "manipur": ("Zone 1", 1), "meghalaya": ("Zone 1", 1),
    "mizoram": ("Zone 2", 1), "nagaland": ("Zone 1", 1),
    "odisha": ("Zone 1", 1), "punjab": ("Zone 2", 2),
    "rajasthan": ("Zone 2", 2), "sikkim": ("Zone 1", 1),
    "telangana": ("Zone 1", 1), "tripura": ("Zone 1", 1),
    "uttar pradesh": ("Zone 2", 2), "uttarakhand": ("Zone 2", 2),
    "j&k": ("Zone 2", 2), "jammu and kashmir": ("Zone 2", 2),
    "ncr": ("Zone 2", 2), "chandigarh": ("Zone 2", 2),
    "delhi": ("Zone 1", 2), "maharashtra": ("Zone 1", 1),
}
HDFC_CITY_ZONES = {
    "kamrup": ("Zone 1", 1), "nagaon": ("Zone 2", 1),
    "bangalore": ("Zone 1", 1), "bengaluru": ("Zone 1", 1),
    "ahmedabad": ("Zone 1", 1), "vadodara": ("Zone 1", 1),
    "daman": ("Zone 1", 1), "dadra & nagar haveli": ("Zone 1", 1),
}


class HDFCAdapter:
    """HDFC private-car OD grid with PDF-backed geography and slab lookup."""
    card_version = HDFC_CARD_VERSION

    def __init__(self, rate_card_root: str | Path):
        self.path = Path(rate_card_root) / "hdfc-ergo" / "feb-2025" / HDFC_FILENAME

    def rules(self) -> list[NormalizedRateRule]:
        parsed = parse_pdf(self.path)
        page = parsed["pages"][0]
        if len(page["tables"]) < 2:
            return []
        rules: list[NormalizedRateRule] = []
        slab_names = list(SLAB_ROWS)
        for zone, table_number in (("Zone 1", 1), ("Zone 2", 2)):
            table = page["tables"][table_number - 1]
            for slab_index, slab in enumerate(slab_names):
                row_number = SLAB_ROWS[slab]
                cells = table["rows"][row_number - 1]["cells"]
                for col_index, raw in enumerate(cells[1:7], 2):
                    # PyMuPDF splits trailing punctuation in these source cells (e.g. 1750% + .).
                    digits = re.sub(r"\D", "", str(raw or ""))
                    if not digits:
                        rate = None
                    else:
                        rate = Decimal(digits) / Decimal(100)
                    if col_index in (2, 5):
                        fuel, ncb = "petrol", "any"
                    elif col_index in (3, 6):
                        fuel, ncb = "non-petrol", "NCB"
                    else:
                        fuel, ncb = "non-petrol", "Non-NCB"
                    product = "Package" if col_index <= 4 else "SAOD"
                    ref = SourceRef(parsed["document_name"], parsed["sha256"], page=1,
                                    table=table_number, row=row_number, column=col_index)
                    rules.append(NormalizedRateRule(
                        insurer_key="hdfc-ergo", card_version=HDFC_CARD_VERSION,
                        conditions={"zone": zone, "product": product, "fuel_group": fuel,
                                    "ncb_state": ncb, "od_premium_band": slab},
                        component=Component.OD, rate_percent=rate, rate_basis="OD premium",
                        source_value=SourceValue(ref, raw, note="Raw PDF table cell; parser retains original cell text."),
                    ))
        return rules

    def rate(self, policy: PolicyInput, product: str, source_sha: str | None = None) -> tuple[ComponentDecision, ComponentDecision]:
        od = ComponentDecision(Component.OD, DecisionStatus.AMBIGUOUS, True)
        card_hash = (hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None)
        od.evidence = [SourceRef(HDFC_FILENAME, card_hash, page=1, table=1,
                                 role="candidate_OD_rate_table")]
        tp_ref = SourceRef(HDFC_FILENAME, card_hash, page=1, table=1, row=2,
                           role="missing_component_evidence")
        # The HDFC grid is an OD payout grid: its Package and SAOD columns are applied
        # to the OD premium and it has no TP column, so no TP commission is payable
        # under this card for Package policies.
        tp = ComponentDecision(Component.TP, DecisionStatus.NOT_APPLICABLE, False, evidence=[tp_ref],
                               issues=["HDFC pays this grid on the OD premium only; the card has no TP payout column."])
        if product == "SAOD":
            tp = ComponentDecision(Component.TP, DecisionStatus.NOT_APPLICABLE, False)
        if product == "SATP":
            od = ComponentDecision(Component.OD, DecisionStatus.NOT_APPLICABLE, False)
            tp = ComponentDecision(Component.TP, DecisionStatus.UNSUPPORTED, True, evidence=[tp_ref],
                                   issues=["The supplied HDFC grid has no standalone-TP (SATP) payout rate."])
            return od, tp
        zone, zone_evidence, zone_issue = self._resolve_zone(policy, card_hash)
        if zone_issue:
            od.issues.append(zone_issue)
            return od, tp
        band = policy.od_premium_band
        if band is None:
            band, issue = hdfc_band_from_premium(policy.od_premium)
            if issue:
                od.issues.append(issue)
                return od, tp
        if band not in SLAB_ROWS:
            od.issues.append(f"Unsupported HDFC premium slab '{band}'.")
            return od, tp
        band_evidence_key = "od_premium" if policy.od_premium is not None else "od_premium_band"
        if not policy.source_evidence.get(band_evidence_key):
            od.issues.append("OD premium/slab was supplied without policy-page evidence.")
            return od, tp
        if not policy.fuel:
            od.issues.append("Fuel information is missing.")
            return od, tp
        if policy.fuel.casefold() not in {"petrol", "diesel", "cng", "lpg", "electric", "ev", "hybrid"}:
            od.issues.append(f"HDFC fuel '{policy.fuel}' cannot be mapped to Petrol or Non-Petrol without an explicit source rule.")
            return od, tp
        if not policy.source_evidence.get("fuel"):
            od.issues.append("Fuel was supplied without policy-page evidence.")
            return od, tp
        fuel_value = policy.fuel.casefold()
        fuel_group = "petrol" if fuel_value in {"petrol", "electric", "ev", "hybrid"} else "non-petrol"
        ncb = policy.ncb_state
        if (policy.business_type or "").casefold() in {"new", "new business"}:
            ncb = "NCB"
        if fuel_group == "non-petrol" and ncb not in {"NCB", "Non-NCB"}:
            od.issues.append("NCB state is required for non-petrol HDFC package/SAOD lookup.")
            return od, tp
        if fuel_group == "non-petrol" and not policy.source_evidence.get("ncb_state") and (policy.business_type or "").casefold() not in {"new", "new business"}:
            od.issues.append("NCB state was supplied without policy-page evidence.")
            return od, tp
        if fuel_group == "petrol":
            ncb = "any"
        if not self.path.exists():
            od.status = DecisionStatus.UNSUPPORTED
            od.issues.append(f"HDFC source file is missing: {self.path.name}.")
            return od, tp
        file_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        mapping_note = SourceRef(HDFC_FILENAME, file_sha, page=1, role="fuel/NCB instruction")
        if fuel_value in {"electric", "ev", "hybrid", "cng", "lpg"}:
            od.evidence.append(mapping_note)
        if (policy.business_type or "").casefold() in {"new", "new business"}:
            od.evidence.append(mapping_note)
        candidates = [rule for rule in self.rules()
                      if rule.conditions == {"zone": zone, "product": product,
                          "fuel_group": fuel_group, "ncb_state": ncb, "od_premium_band": band}]
        if len(candidates) != 1:
            od.status = DecisionStatus.AMBIGUOUS
            od.issues.append(f"Expected one HDFC source row, found {len(candidates)}.")
            return od, tp
        rule = candidates[0]
        status, issue = exception_decision(rule)
        od.status = status
        od.rate_percent = rule.rate_percent
        od.rate_basis = rule.rate_basis
        od.selected_conditions = rule.conditions
        od.evidence = [*zone_evidence, *policy.source_evidence.get("fuel", []),
                       *policy.source_evidence.get("ncb_state", []),
                       *policy.source_evidence.get(band_evidence_key, []), *od.evidence, rule.source_value.ref]
        if issue:
            od.issues.append(issue)
        # Calculate commission amount when OD premium is available
        if od.status == DecisionStatus.RESOLVED and od.rate_percent is not None and policy.od_premium is not None:
            od.premium_basis = policy.od_premium
            od.commission_amount = (
                policy.od_premium * od.rate_percent / Decimal("100")
            ).quantize(Decimal("0.01"))
            od.calculation = (
                f"OD premium {policy.od_premium} × {od.rate_percent}% = {od.commission_amount}"
            )
        return od, tp

    def _resolve_zone(self, policy: PolicyInput, card_hash: str | None) -> tuple[str | None, list[SourceRef], str | None]:
        """Use an explicit zone, or an exact state/city from the HDFC PDF table."""
        if policy.zone:
            if policy.zone not in {"Zone 1", "Zone 2"}:
                return None, [], f"Unrecognized HDFC zone '{policy.zone}'."
            evidence = policy.source_evidence.get("zone", [])
            if not evidence:
                return None, [], "Zone was supplied without a source reference; geography cannot be verified."
            return policy.zone, evidence, None

        geography = (policy.geography or "").casefold().strip()
        match = HDFC_CITY_ZONES.get(geography) or HDFC_STATE_ZONES.get(geography)
        state_evidence = policy.source_evidence.get("state", [])
        if match and state_evidence:
            zone, page = match
            return zone, [*state_evidence, SourceRef(HDFC_FILENAME, card_hash, page=page,
                table=3 if page == 1 else 1, role="HDFC_zone_mapping")], None
        if match:
            return None, [], "HDFC geography was supplied without policy-page evidence."
        return None, [], (
            "HDFC zone cannot be resolved: provide an explicit PDF-backed zone or an exact state/city covered by the HDFC geography table. "
            "RTO codes are not converted to a state because the source PDF does not provide an RTO mapping."
        )
