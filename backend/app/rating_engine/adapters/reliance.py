"""Reliance General 4W private-car rate adapter.

Source: Reliance Broking Premier  FEB 26 Grid.xlsx

Implemented sheet: PRIVATE CAR COMP, SAOD & STP
  - Title: 'Pvt Car Old Business Grid- Jan-26'
  - Columns: Zone, RTO region, Petrol/Bifuel/Comp, Diesel/EV/Comp, SA OD, STP
  - Rates are stated as percentage points (25 = 25%)

Adjustments (from same sheet, T&C column):
  - <1000 CC: payout is 5 percentage-points less than grid rate.
    Source says "5% lesser than the above Grid" — interpreted as 5 pp reduction.
  - Standalone ZD policies: 2.5 pp reduction.
  - EW (Extended Warranty): flat 20% payout.
  - Tyre/RTI add-on bundle sourced: +2.5 pp additional payout.

Grid precedence:
  - 'PRIVATE CAR COMP, SAOD & STP': described as "Pvt Car Old Business Grid"
  - 'FEB'26 - Grid': contains CV and commercial segments; private car not found
    there in a comparable structure (the FEB'26 Grid rows are for CV, school bus,
    taxi etc., not private car COMP/SAOD/STP).
  - Decision: PRIVATE CAR COMP, SAOD & STP is used for private-car.
    Source evidence: sheet title and column headers explicitly name the product.

NOTE: STP rate is 0 in all rows of PRIVATE CAR COMP, SAOD & STP. Returned as
      RESOLVED with 0.00%.

RTO mapping uses 'RTO List' sheet (Region_Code, Column1=RTO code, Region_City, Zone).
  - Region_City is used to match against the RTO region text in the rate grid.
  - Zone is used for zone matching.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import openpyxl

from ..models import (Component, ComponentDecision, DecisionStatus,
                      PolicyInput, SourceRef)

RELIANCE_FILENAME = "Reliance Broking Premier  FEB 26 Grid.xlsx"
RELIANCE_CARD_VERSION = "February 2026 (Pvt Car Old Business Grid Jan-26)"
_SHEET_PC = "PRIVATE CAR COMP, SAOD & STP"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Rate grid hard-coded from source (read once, used deterministically)
# Columns: zone, rto_region, petrol_comp, diesel_ev_comp, saod, stp
# ---------------------------------------------------------------------------
_RATE_GRID = [
    # Zone,     Region pattern(s),                   Petrol, Diesel, SAOD,  STP
    ("WEST",    "mumbai, pune, goa",                 25,     10,     25,    0),
    ("WEST",    "rest of maharashtra",               22.5,   10,     25,    0),
    ("WEST",    "gujrat",                            20,     10,     25,    0),
    ("WEST",    "madhya pradesh",                    15,     5,      15,    0),
    ("SOUTH",   "banglore, hyderabad",               22.5,   10,     25,    0),
    ("SOUTH",   "rest of ka,ts,ap",                 15,     5,      25,    0),
    ("SOUTH",   "kerala",                            12.5,   5,      25,    0),
    ("SOUTH",   "tamilnadu",                         12.5,   5,      20,    0),
    ("NORTH",   "delhi",                             22.5,   10,     20,    0),
    ("NORTH",   "punjab, hp , jk",                  20,     7.5,    20,    0),
    ("NORTH",   "up, haryana , rajasthan",           12.5,   5,      15,    0),
    ("EAST",    "ne , odisha, chhattisgarh",         15,     10,     25,    0),
    ("EAST",    "bihar , jharkhand",                 22.5,   10,     25,    0),
    ("EAST",    "kolkata",                           22.5,   10,     25,    0),
    ("EAST",    "west bengal",                       15,     10,     25,    0),
]

# RTO city → zone/region mapping helpers
_CITY_REGION_MAP: dict[str, tuple[str, str]] = {
    # WEST
    "mumbai": ("WEST", "mumbai, pune, goa"),
    "pune": ("WEST", "mumbai, pune, goa"),
    "goa": ("WEST", "mumbai, pune, goa"),
    "ahmednagar": ("WEST", "rest of maharashtra"),
    "aurangabad": ("WEST", "rest of maharashtra"),
    "kolhapur": ("WEST", "rest of maharashtra"),
    "nashik": ("WEST", "rest of maharashtra"),
    "solapur": ("WEST", "rest of maharashtra"),
    "nagpur": ("WEST", "rest of maharashtra"),
    "rom": ("WEST", "rest of maharashtra"),
    "maharashtra": ("WEST", "rest of maharashtra"),
    "ahmedabad": ("WEST", "gujrat"),
    "surat": ("WEST", "gujrat"),
    "vadodara": ("WEST", "gujrat"),
    "gandhidham": ("WEST", "gujrat"),
    "jamnagar": ("WEST", "gujrat"),
    "rajkot": ("WEST", "gujrat"),
    "vapi": ("WEST", "gujrat"),
    "gujarat": ("WEST", "gujrat"),
    "madhya pradesh": ("WEST", "madhya pradesh"),
    "bhopal": ("WEST", "madhya pradesh"),
    "indore": ("WEST", "madhya pradesh"),
    # SOUTH
    "bangalore": ("SOUTH", "banglore, hyderabad"),
    "bengaluru": ("SOUTH", "banglore, hyderabad"),
    "hyderabad": ("SOUTH", "banglore, hyderabad"),
    "karnataka": ("SOUTH", "rest of ka,ts,ap"),
    "mangalore": ("SOUTH", "rest of ka,ts,ap"),
    "mysore": ("SOUTH", "rest of ka,ts,ap"),
    "telangana": ("SOUTH", "rest of ka,ts,ap"),
    "andhra pradesh": ("SOUTH", "rest of ka,ts,ap"),
    "kerala": ("SOUTH", "kerala"),
    "calicut": ("SOUTH", "kerala"),
    "cochin": ("SOUTH", "kerala"),
    "trivandrum": ("SOUTH", "kerala"),
    "chennai": ("SOUTH", "tamilnadu"),
    "coimbatore": ("SOUTH", "tamilnadu"),
    "erode": ("SOUTH", "tamilnadu"),
    "madurai": ("SOUTH", "tamilnadu"),
    "pondicherry": ("SOUTH", "tamilnadu"),
    "tamilnadu": ("SOUTH", "tamilnadu"),
    "tamil nadu": ("SOUTH", "tamilnadu"),
    # NORTH
    "delhi": ("NORTH", "delhi"),
    "punjab": ("NORTH", "punjab, hp , jk"),
    "himachal pradesh": ("NORTH", "punjab, hp , jk"),
    "jammu": ("NORTH", "punjab, hp , jk"),
    "kashmir": ("NORTH", "punjab, hp , jk"),
    "uttar pradesh": ("NORTH", "up, haryana , rajasthan"),
    "haryana": ("NORTH", "up, haryana , rajasthan"),
    "rajasthan": ("NORTH", "up, haryana , rajasthan"),
    "jaipur": ("NORTH", "up, haryana , rajasthan"),
    "lucknow": ("NORTH", "up, haryana , rajasthan"),
    # EAST
    "ne": ("EAST", "ne , odisha, chhattisgarh"),
    "northeast": ("EAST", "ne , odisha, chhattisgarh"),
    "odisha": ("EAST", "ne , odisha, chhattisgarh"),
    "chhattisgarh": ("EAST", "ne , odisha, chhattisgarh"),
    "bhubaneswar": ("EAST", "ne , odisha, chhattisgarh"),
    "bhubaneshwar": ("EAST", "ne , odisha, chhattisgarh"),
    "bihar": ("EAST", "bihar , jharkhand"),
    "jharkhand": ("EAST", "bihar , jharkhand"),
    "patna": ("EAST", "bihar , jharkhand"),
    "kolkata": ("EAST", "kolkata"),
    "west bengal": ("EAST", "west bengal"),
}


class RelianceAdapter:
    """Reliance General 4W private-car rate adapter."""
    insurer_key = "reliance-indusind"
    card_version = RELIANCE_CARD_VERSION

    def __init__(self, rate_card_root: str | Path):
        self.root = Path(rate_card_root)
        self._path = self.root / "reliance-indusind" / "feb-2026" / RELIANCE_FILENAME

    def rate(self, policy: PolicyInput, product: str) -> tuple[ComponentDecision, ComponentDecision]:
        od_applicable = product != "SATP"
        tp_applicable = product != "SAOD"

        od = ComponentDecision(Component.OD,
                               DecisionStatus.NOT_APPLICABLE if not od_applicable else DecisionStatus.AMBIGUOUS,
                               od_applicable)
        tp = ComponentDecision(Component.TP,
                               DecisionStatus.NOT_APPLICABLE if not tp_applicable else DecisionStatus.AMBIGUOUS,
                               tp_applicable)

        if not self._path.exists():
            msg = f"Reliance source file missing: {RELIANCE_FILENAME}"
            if od_applicable:
                od.issues.append(msg)
            if tp_applicable:
                tp.issues.append(msg)
            return od, tp

        file_sha = _sha256(self._path)

        # Resolve zone/region from RTO or geography
        zone, region, geo_issues = self._resolve_geography(policy, file_sha)
        if geo_issues:
            if od_applicable:
                od.issues.extend(geo_issues)
            if tp_applicable:
                tp.issues.extend(geo_issues)
            return od, tp

        # Resolve fuel group
        fuel_group, fuel_issues = self._resolve_fuel(policy)
        if fuel_issues:
            if od_applicable:
                od.issues.extend(fuel_issues)
            if tp_applicable:
                tp.issues.extend(fuel_issues)
            return od, tp

        # Look up the matching grid row
        grid_row = self._find_grid_row(zone, region)
        if grid_row is None:
            msg = f"Reliance: no grid row found for zone={zone!r}, region={region!r}."
            if od_applicable:
                od.issues.append(msg)
            if tp_applicable:
                tp.issues.append(msg)
            return od, tp

        grid_zone, grid_region, petrol_pct, diesel_pct, saod_pct, stp_pct = grid_row
        # Find the row number in the actual sheet for evidence
        row_num = self._find_row_number(zone, region, file_sha)

        # Select base rate
        if product == "Package":
            od_base = Decimal(str(petrol_pct if fuel_group == "petrol" else diesel_pct))
            tp_base = Decimal(str(stp_pct))  # STP is always 0 in this grid
        elif product == "SAOD":
            od_base = Decimal(str(saod_pct))
            tp_base = None
        elif product == "SATP":
            od_base = None
            tp_base = Decimal(str(stp_pct))
        else:
            od.issues.append(f"Reliance: unrecognised product '{product}'.")
            tp.issues.append(f"Reliance: unrecognised product '{product}'.")
            return od, tp

        selected_conditions = {
            "zone": zone, "region": region, "fuel_group": fuel_group, "product": product
        }
        evidence_refs = [
            SourceRef(RELIANCE_FILENAME, file_sha, sheet=_SHEET_PC,
                      cell=f"A{row_num}" if row_num else None, role="rate_row")
        ]

        # Apply adjustments
        engine_cc = policy.engine_cc
        has_zd = self._has_zero_dep(policy)
        has_tyre_rti = self._has_tyre_rti(policy)

        # Grid adjustments (sheet note, cell H3). The workbook does not say whether
        # "5% lesser" is relative or in percentage points; broker grids quote payout
        # changes in percentage points, so they are applied that way and disclosed
        # as assumptions on the decision. Adjustments apply to the OD payout only
        # (the private-car STP payout is 0%), and a rate never drops below zero.
        addon_text = " ".join(policy.add_ons or ()).casefold()
        add_on_count = len(policy.add_ons or ())
        standalone_zd = has_zd and add_on_count == 1
        adj_notes: list[str] = []
        assumptions: list[str] = []
        adj_ref = SourceRef(RELIANCE_FILENAME, file_sha, sheet=_SHEET_PC,
                            cell="H3", role="adjustment_instruction")
        if "extended warranty" in addon_text or " ew" in f" {addon_text}":
            assumptions.append("Assumption: the Extended Warranty flat payout is paid separately and is not "
                               "included in this grid commission.")

        def apply_adjustments(base_pct: Decimal | None) -> Decimal | None:
            if base_pct is None:
                return None
            rate = base_pct
            notes_local = []
            if engine_cc is not None and engine_cc < 1000:
                rate -= Decimal("5")
                notes_local.append("<1000 CC: -5 percentage points ('Payout for <1000 CC, PO will be 5% lesser than the above Grid')")
            if standalone_zd:
                rate -= Decimal("2.5")
                notes_local.append("Standalone ZD: -2.5 percentage points ('Standalone ZD policies 2.5% will be reduced')")
            if has_tyre_rti:
                rate += Decimal("2.5")
                notes_local.append("Tyre/RTI bundle: +2.5 percentage points ('Addon Bundle (Tyre/RTI) if Sourced, 2.5% Additional Payout')")
            if notes_local:
                adj_notes.extend(n for n in notes_local if n not in adj_notes)
                assumptions.append("Assumption: grid adjustments are applied in percentage points.")
                if adj_ref not in evidence_refs:
                    evidence_refs.append(adj_ref)
            return max(rate, Decimal("0"))

        if od_applicable and od_base is not None:
            od_rate = apply_adjustments(od_base)
            od_ref = SourceRef(RELIANCE_FILENAME, file_sha, sheet=_SHEET_PC,
                               cell=f"C{row_num}" if row_num else None, role="rate_cell")
            od.evidence = evidence_refs + [od_ref]
            od.selected_conditions = {**selected_conditions, "adjustments": adj_notes.copy()}
            od.rate_percent = od_rate
            od.rate_basis = "OD premium"
            od.status = DecisionStatus.RESOLVED
            if policy.od_premium is not None:
                od.premium_basis = policy.od_premium
                od.commission_amount = (
                    policy.od_premium * od_rate / Decimal("100")
                ).quantize(Decimal("0.01"))
                od.calculation = (
                    f"OD premium {policy.od_premium} × {od_rate}% = {od.commission_amount}"
                )

        if tp_applicable and tp_base is not None:
            # STP rate is always 0 in the Reliance private-car grid
            tp_rate = tp_base
            tp_ref = SourceRef(RELIANCE_FILENAME, file_sha, sheet=_SHEET_PC,
                               cell=f"F{row_num}" if row_num else None, role="rate_cell")
            tp.evidence = evidence_refs + [tp_ref]
            tp.selected_conditions = {**selected_conditions, "adjustments": adj_notes.copy()}
            tp.rate_percent = tp_rate
            tp.rate_basis = "TP premium"
            tp.status = DecisionStatus.RESOLVED
            if policy.tp_premium is not None and tp_rate is not None:
                tp.premium_basis = policy.tp_premium
                tp.commission_amount = (
                    policy.tp_premium * tp_rate / Decimal("100")
                ).quantize(Decimal("0.01"))
                tp.calculation = (
                    f"TP premium {policy.tp_premium} × {tp_rate}% = {tp.commission_amount}"
                )

        # Adjustments and the EW note concern the OD payout only.
        if od.applicable and od.status == DecisionStatus.RESOLVED:
            od.issues.extend(a for a in dict.fromkeys(assumptions) if a not in od.issues)

        # Adjustments and the EW note concern the OD payout only.
        if od.applicable and od.status == DecisionStatus.RESOLVED:
            od.issues.extend(a for a in dict.fromkeys(assumptions) if a not in od.issues)

        # SATP: OD not applicable; mark explicitly
        if product == "SATP":
            od = ComponentDecision(Component.OD, DecisionStatus.NOT_APPLICABLE, False)

        # SAOD: TP not applicable
        if product == "SAOD":
            tp = ComponentDecision(Component.TP, DecisionStatus.NOT_APPLICABLE, False)

        return od, tp

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _resolve_geography(self, policy: PolicyInput,
                           file_sha: str) -> tuple[str | None, str | None, list[str]]:
        """Resolve zone and region from policy RTO or geography field."""
        rto = (policy.rto or "").strip()
        geo = (policy.geography or "").strip()

        if not rto and not geo:
            return None, None, [
                "RTO or state/geography is required for Reliance regional grid lookup."
            ]

        # Try RTO first
        if rto:
            rto_lower = rto.lower()
            for key, (zone, region) in _CITY_REGION_MAP.items():
                if key in rto_lower or rto_lower in key:
                    return zone, region, []

        # Try geography/state
        if geo:
            geo_lower = geo.lower()
            for key, (zone, region) in _CITY_REGION_MAP.items():
                if key in geo_lower or geo_lower in key:
                    return zone, region, []

        return None, None, [
            f"Reliance: RTO '{policy.rto}' and geography '{policy.geography}' could not be mapped to a "
            "grid region. Exact region matching requires either a city name or state from the "
            "Reliance PRIVATE CAR COMP, SAOD & STP rate grid."
        ]

    def _resolve_fuel(self, policy: PolicyInput) -> tuple[str | None, list[str]]:
        fuel = (policy.fuel or "").lower().strip()
        if not fuel:
            return None, ["Fuel type is required for Reliance private-car rate lookup (Petrol/Bifuel vs Diesel/EV)."]
        if fuel in {"petrol", "cng", "lpg", "bifuel", "hybrid"}:
            return "petrol", []
        if fuel in {"diesel", "electric", "ev"}:
            return "diesel", []
        return None, [f"Reliance: fuel '{fuel}' cannot be classified as Petrol/Bifuel or Diesel/EV."]

    def _find_grid_row(self, zone: str | None, region: str | None) -> tuple | None:
        if zone is None or region is None:
            return None
        region_lower = region.lower()
        for row in _RATE_GRID:
            if row[1].lower() == region_lower:
                return row
        return None

    def _find_row_number(self, zone: str | None, region: str | None, file_sha: str) -> int | None:
        """Find the actual Excel row number for the matching grid entry (1-indexed)."""
        if zone is None or region is None:
            return None
        wb = openpyxl.load_workbook(self._path, data_only=True, read_only=True)
        try:
            ws = wb[_SHEET_PC]
            region_lower = region.lower()
            for row_idx, row in enumerate(ws.iter_rows(min_row=1, values_only=True), start=1):
                cell_val = str(row[1] or "").strip().lower()
                if region_lower in cell_val or cell_val in region_lower:
                    return row_idx
        finally:
            wb.close()
        return None

    def _has_zero_dep(self, policy: PolicyInput) -> bool:
        """Check if the policy has standalone zero-depreciation cover."""
        # Reliance schedules print zero-depreciation cover as "Nil Depreciation".
        return any(term in item.casefold() for item in (policy.add_ons or ())
                   for term in ("zero dep", "nil dep"))

    def _has_tyre_rti(self, policy: PolicyInput) -> bool:
        """Check if Tyre/RTI add-on bundle is present."""
        items = " ".join(policy.add_ons or ()).casefold()
        return "tyre" in items or "rti" in items or "return to invoice" in items
