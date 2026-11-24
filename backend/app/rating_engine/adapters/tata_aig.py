"""Tata AIG private-car rate adapter.

Source: Tata AIG Standard Grid_Communication_Mar'26_F_v2_0212.xlsx

Implements: Pvtcar sheet — base commission lookup.

Key design decisions (all sourced from General Guidelines and Pvtcar sheet):

Premium basis (General Guidelines, item 4):
  - Package: commission % on OD premium.
  - SAOD: commission % on OD premium.
  - SATP: commission % on Net Premium.
  - LTTP: not considered for premium slab or payout % (item 6).

Pvtcar sheet structure (row 5 = header):
  Cols 1–12: Type, Business Type, Fuel Type, Section Text, NCB, Add On + lookup key cols
  Cols 13–70: Territory commission values (decimal; 0.20 = 20%).

GWP slab increments (pci checks sheet):
  - Additional percentages based on GWP slab achievement.
  - The base + increment architecture is confirmed from General Guidelines item 2.
  - However, GWP slab calculation requires policy-level and portfolio-level GWP data
    which is not available from a single policy PDF.
  - Status: GWP-based increments are flagged as AMBIGUOUS / not applicable without
    external GWP data. Base commission is returned as RESOLVED where verifiable.

Territory mapping:
  - Territory column names are sourced directly from row 5 of Pvtcar sheet.
  - RTO/city → territory requires Tata AIG's internal RTO mapping.
  - The workbook does not contain a Pvtcar-specific RTO cluster mapping sheet.
  - The territory is the policy's state/city when it names a territory column
    exactly (e.g. DELHI); otherwise the reviewer selects it.

HE/UHE vs Other than HE/UHE:
  - The workbook uses these two type categories.
  - 'Compact', 'MPV SUV', 'Mid Size', 'Ultra High End', 'Mini', 'High End' appear
    in the Type column of the lookup table.
  - The workbook has no make/model -> segment table, so the reviewer selects the
    segment.

Fuel: rows for CNG and Electric are preferred over "Other Than Diesel" when present.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import openpyxl

from ..models import (Component, ComponentDecision, DecisionStatus,
                      PolicyInput, SourceRef)

TATA_FILENAME = "Tata AIG Standard Grid_Communication_Mar'26_F_v2_0212.xlsx"
TATA_CARD_VERSION = "March 2026 file; standard grid effective 1 Nov 2025"
_SHEET_PVTCAR = "Pvtcar"
_SHEET_GUIDELINES = "General Guidelines"
_SHEET_PCI = "pci checks"

# ---------------------------------------------------------------------------
# Territory column index mapping (1-indexed, as in the Excel sheet)
# ---------------------------------------------------------------------------
_TERRITORY_COLS: dict[str, int] = {
    "AHMEDABAD": 13,
    "ANDRA PRADESH": 14,
    "ANDHRA PRADESH": 14,
    "BANGALORE": 15,
    "BHUBANESHWAR": 16,
    "BIHAR": 17,
    "CHHATTISGARH": 18,
    "CHANDIGARH": 19,
    "CHENNAI": 20,
    "COIMBATORE": 21,
    "DELHI": 22,
    "GOA": 23,
    "HARYANA": 24,
    "HIMACHAL PRADESH": 25,
    "HYDERABAD": 26,
    "INDORE": 27,
    "JAMMU & KASHMIR": 28,
    "JAMMU AND KASHMIR": 28,
    "JAIPUR": 29,
    "JHARKHAND": 30,
    "KA1": 31,
    "KA2": 32,
    "KERALA": 33,
    "KOLKATA": 34,
    "MP1": 35,
    "MP2": 36,
    "MP3": 37,
    "MUMBAI": 38,
    "NAGPUR": 39,
    "PB1": 40,
    "PB2": 41,
    "PUNE": 42,
    "RAJKOT": 43,
    "RJ1": 44,
    "RJ2": 45,
    "RJ3": 46,
    "RJ4": 47,
    "RJ5": 48,
    "ROE": 49,
    "ROGJ": 50,
    "ROM1": 51,
    "ROM2": 52,
    "ROM3": 53,
    "ROM4": 54,
    "ROOD": 55,
    "ROTN": 56,
    "ROWB": 57,
    "SURAT": 58,
    "TELENGANA": 59,
    "TELANGANA": 59,
    "UP1": 60,
    "UP2": 61,
    "UP3": 62,
    "UTTARAKHAND": 63,
    "VADODARA": 64,
    "VIJAYWADA": 65,
    "VIJAYAWADA": 65,
    "VISHAKAPATNAM": 66,
    "VISAKHAPATNAM": 66,
    "ROWB2": 67,
}

# These aliases are display-name normalizations only.  They are not an RTO mapping:
# callers must provide the actual territory selected from the source workbook.
_TERRITORY_ALIASES: dict[str, str] = {
    "ahmedabad": "AHMEDABAD",
    "andhra pradesh": "ANDHRA PRADESH",
    "ap": "ANDHRA PRADESH",
    "bangalore": "BANGALORE",
    "bengaluru": "BANGALORE",
    "bhubaneswar": "BHUBANESHWAR",
    "bhubaneshwar": "BHUBANESHWAR",
    "bihar": "BIHAR",
    "chhattisgarh": "CHHATTISGARH",
    "chandigarh": "CHANDIGARH",
    "chennai": "CHENNAI",
    "coimbatore": "COIMBATORE",
    "delhi": "DELHI",
    "goa": "GOA",
    "haryana": "HARYANA",
    "himachal pradesh": "HIMACHAL PRADESH",
    "hp": "HIMACHAL PRADESH",
    "hyderabad": "HYDERABAD",
    "indore": "INDORE",
    "jammu": "JAMMU & KASHMIR",
    "kashmir": "JAMMU & KASHMIR",
    "jk": "JAMMU & KASHMIR",
    "jaipur": "JAIPUR",
    "jharkhand": "JHARKHAND",
    "kerala": "KERALA",
    "calicut": "KERALA",
    "cochin": "KERALA",
    "trivandrum": "KERALA",
    "kolkata": "KOLKATA",
    "mumbai": "MUMBAI",
    "pune": "PUNE",
    "rajkot": "RAJKOT",
    "surat": "SURAT",
    "telangana": "TELENGANA",
    "telengana": "TELENGANA",
    "uttarakhand": "UTTARAKHAND",
    "vadodara": "VADODARA",
    "vijayawada": "VIJAYWADA",
    "visakhapatnam": "VISHAKAPATNAM",
    "vishakhapatnam": "VISHAKAPATNAM",
    "nagpur": "NAGPUR",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


class TataAIGAdapter:
    """Tata AIG private-car rate adapter."""
    insurer_key = "tata-aig"
    card_version = TATA_CARD_VERSION

    def __init__(self, rate_card_root: str | Path):
        self.root = Path(rate_card_root)
        self._path = self.root / "tata-aig" / "march-2026" / TATA_FILENAME

    def rate(self, policy: PolicyInput, product: str) -> tuple[ComponentDecision, ComponentDecision]:
        od_applicable = product != "SATP"
        # The supplied General Guidelines establish OD as the Package/SAOD basis.
        # They do not provide a separate Package TP payout rate.
        tp_applicable = product == "SATP"

        od = ComponentDecision(Component.OD,
                               DecisionStatus.NOT_APPLICABLE if not od_applicable else DecisionStatus.AMBIGUOUS,
                               od_applicable)
        tp = ComponentDecision(Component.TP,
                               DecisionStatus.NOT_APPLICABLE if not tp_applicable else DecisionStatus.AMBIGUOUS,
                               tp_applicable)

        if not self._path.exists():
            msg = f"Tata AIG source file missing: {TATA_FILENAME}"
            if od_applicable:
                od.issues.append(msg)
            if tp_applicable:
                tp.issues.append(msg)
            return od, tp

        file_sha = _sha256(self._path)

        # Resolve territory
        territory, territory_issues = self._resolve_territory(policy, file_sha)
        if territory_issues:
            if od_applicable:
                od.issues.extend(territory_issues)
            if tp_applicable:
                tp.issues.extend(territory_issues)
            return od, tp

        # Resolve fuel type
        fuel_type, fuel_issues = self._resolve_fuel(policy)
        if fuel_issues:
            if od_applicable:
                od.issues.extend(fuel_issues)
            if tp_applicable:
                tp.issues.extend(fuel_issues)
            return od, tp

        # Map product to section_text
        section_text = self._product_to_section(product)

        # Resolve vehicle type/segment
        vehicle_type, segment, type_issues = self._resolve_vehicle_type(policy)

        # Build lookup key: (Type, Business Type, Fuel Type, Section Text, NCB, Add On)
        # Business type
        business_type, business_issues = self._map_business_type(policy)

        # NCB
        ncb, ncb_issues = self._map_ncb(policy, product)

        # A missing selector cannot be filled with a plausible default.  Returning
        # before the workbook lookup keeps the decision explicitly unresolved.
        if type_issues or business_issues or ncb_issues:
            issues = type_issues + business_issues + ncb_issues
            for decision in (od, tp):
                if decision.applicable:
                    decision.issues.extend(issues)
            return od, tp

        # Look up in Pvtcar sheet
        rate_decimal, row_num, lookup_issues = self._lookup_pvtcar(
            vehicle_type=vehicle_type,
            segment=segment,
            business_type=business_type,
            fuel_type=fuel_type,
            section_text=section_text,
            ncb=ncb,
            territory=territory,
            file_sha=file_sha,
            add_on=self._add_on_flag(policy),
        )

        all_issues = type_issues + business_issues + ncb_issues + lookup_issues

        source_ref = SourceRef(TATA_FILENAME, file_sha, sheet=_SHEET_PVTCAR,
                               cell=f"A{row_num}" if row_num else None, role="rate_row")
        guidelines_ref = SourceRef(TATA_FILENAME, file_sha, sheet=_SHEET_GUIDELINES,
                                   cell="C4", role="premium_basis_instruction")

        selected_conditions = {
            "vehicle_type": vehicle_type,
            "segment": segment,
            "business_type": business_type,
            "fuel_type": fuel_type,
            "section_text": section_text,
            "ncb": ncb,
            "territory": territory,
        }

        if od_applicable:
            od.evidence = [source_ref, guidelines_ref]
            od.selected_conditions = selected_conditions.copy()

            if all_issues and rate_decimal is None:
                od.issues.extend(all_issues)
            elif rate_decimal is not None:
                rate_pct = Decimal(str(rate_decimal)) * Decimal("100")
                od.rate_percent = rate_pct
                od.rate_basis = "OD premium"
                od.status = DecisionStatus.RESOLVED
                od.issues.extend(all_issues)
                if policy.od_premium is not None:
                    od.premium_basis = policy.od_premium
                    od.commission_amount = (
                        policy.od_premium * rate_pct / Decimal("100")
                    ).quantize(Decimal("0.01"))
                    od.calculation = (
                        f"OD premium {policy.od_premium} × {rate_pct}% = {od.commission_amount}"
                    )
                # Note: GWP slab increments are not calculable from single-policy data
                od.issues.append(
                    "Note: GWP-based incremental COA (pci checks sheet) requires portfolio-level GWP data "
                    "not available from a single policy. Base commission only is calculated."
                )
            else:
                od.issues.extend(all_issues)

        if tp_applicable:
            tp.evidence = [source_ref, guidelines_ref]
            tp.selected_conditions = selected_conditions.copy()

            if all_issues and rate_decimal is None:
                tp.issues.extend(all_issues)
            elif rate_decimal is not None:
                rate_pct = Decimal(str(rate_decimal)) * Decimal("100")
                tp.rate_percent = rate_pct
                tp.rate_basis = "Net Premium"  # SATP uses Net Premium as basis
                tp.status = DecisionStatus.RESOLVED
                tp.issues.extend(all_issues)
                if policy.net_premium is not None:
                    tp.premium_basis = policy.net_premium
                    tp.commission_amount = (
                        policy.net_premium * rate_pct / Decimal("100")
                    ).quantize(Decimal("0.01"))
                    tp.calculation = (
                        f"Net Premium {policy.net_premium} × {rate_pct}% = {tp.commission_amount}"
                    )
                tp.issues.append(
                    "Note: GWP-based incremental COA (pci checks sheet) requires portfolio-level GWP data "
                    "not available from a single policy. Base commission only is calculated."
                )
            else:
                tp.issues.extend(all_issues)

        # SATP: OD not applicable
        if product == "SATP":
            od = ComponentDecision(Component.OD, DecisionStatus.NOT_APPLICABLE, False)
        # SAOD: TP not applicable
        if product in {"Package", "SAOD"}:
            tp = ComponentDecision(Component.TP, DecisionStatus.NOT_APPLICABLE, False)

        return od, tp

    # ------------------------------------------------------------------ #
    # Core lookup                                                         #
    # ------------------------------------------------------------------ #

    def _lookup_pvtcar(
        self,
        vehicle_type: str,
        segment: str | None,
        business_type: str,
        fuel_type: str,
        section_text: str,
        ncb: str,
        territory: str,
        file_sha: str,
        add_on: str | None = None,
    ) -> tuple[float | None, int | None, list[str]]:
        """Look up the base commission rate in the Pvtcar sheet.

        Returns (rate_as_decimal, row_number, issues).
        rate_as_decimal is in decimal form (0.20 = 20%).
        """
        territory_col = _TERRITORY_COLS.get(territory.upper())
        if territory_col is None:
            return None, None, [
                f"Tata AIG: territory '{territory}' not found in Pvtcar column map. "
                "Supported territories: " + ", ".join(sorted(_TERRITORY_COLS.keys()))
            ]

        wb = openpyxl.load_workbook(self._path, data_only=True, read_only=True)
        try:
            ws = wb[_SHEET_PVTCAR]
            # Data starts at row 6 (1-indexed), header is row 5
            candidates: list[tuple[int, float]] = []
            for row_idx, row in enumerate(ws.iter_rows(min_row=6, values_only=True), start=6):
                # Columns (0-indexed): 6=Type, 7=Business Type, 8=Fuel Type,
                #                      9=Section Text, 10=NCB, 11=Add On
                r_type = str(row[6] or "").strip()
                r_business = str(row[7] or "").strip()
                r_fuel = str(row[8] or "").strip()
                r_section = str(row[9] or "").strip()
                r_ncb = str(row[10] or "").strip()

                # Match type (HE/UHE or Other than HE/UHE, using segment column)
                type_match = self._type_matches(r_type, vehicle_type, segment)
                business_match = r_business.lower() == business_type.lower()
                fuel_match = self._fuel_matches(r_fuel, fuel_type)
                section_match = r_section.lower() == section_text.lower()
                ncb_match = r_ncb.upper() in {"ALL", ncb.upper()}

                if type_match and business_match and fuel_match and section_match and ncb_match:
                    # territory_col is 1-indexed; row tuple is 0-indexed
                    rate_val = row[territory_col - 1] if territory_col - 1 < len(row) else None
                    if rate_val is not None:
                        try:
                            rate_float = float(rate_val)
                            candidates.append((row_idx, rate_float, r_fuel.lower(), str(row[11] or "").strip().lower()))
                        except (TypeError, ValueError):
                            pass
        finally:
            wb.close()

        if not candidates:
            return None, None, [
                f"Tata AIG Pvtcar: no row matches "
                f"type={vehicle_type!r}, business={business_type!r}, "
                f"fuel={fuel_type!r}, section={section_text!r}, ncb={ncb!r}, territory={territory!r}."
            ]

        # A row for the exact fuel (e.g. CNG) is more specific than "Other Than Diesel".
        exact = [c for c in candidates if c[2] == fuel_type.lower()]
        if exact:
            candidates = exact
        # The Add On column distinguishes policies with and without add-on covers.
        if len({rate for _, rate, _, _ in candidates}) > 1 and add_on is not None:
            by_addon = [c for c in candidates if c[3] in {add_on.lower(), "all"}]
            if by_addon:
                candidates = by_addon
        unique_rates = {rate for _, rate, _, _ in candidates}
        if len(unique_rates) > 1:
            return None, None, [
                f"Tata AIG Pvtcar: {len(candidates)} rows match the lookup conditions with different rates "
                f"({sorted(unique_rates)}). Cannot resolve unambiguously."
            ]
        row_idx, rate, _, _ = candidates[0]
        return rate, row_idx, []

    # ------------------------------------------------------------------ #
    # Matching helpers                                                    #
    # ------------------------------------------------------------------ #

    def _type_matches(self, row_type: str, vehicle_type: str, segment: str | None) -> bool:
        """Match the 'Type' column value against the policy vehicle type/segment."""
        if segment:
            return row_type.lower() == segment.lower()
        if not vehicle_type:
            return True
        rt = row_type.lower()
        vt = vehicle_type.lower()
        if vt in ("all", "any"):
            return True
        if "other than he" in vt:
            return "other than he" in rt or "compact" in rt or "mid size" in rt or "mini" in rt
        if "he/uhe" in vt or "high end" in vt or "ultra" in vt:
            return "he/uhe" in rt or "high end" in rt or "ultra" in rt
        return rt == vt

    def _fuel_matches(self, row_fuel: str, policy_fuel: str) -> bool:
        rf = row_fuel.lower()
        pf = policy_fuel.lower()
        if rf == "all":
            return True
        if pf == "diesel":
            return "diesel" in rf and "other" not in rf
        # A specific CNG/Electric row is preferred by the caller; otherwise any
        # non-diesel fuel falls under "Other Than Diesel".
        return rf == pf or rf == "other than diesel"

    def _resolve_territory(self, policy: PolicyInput,
                           file_sha: str) -> tuple[str | None, list[str]]:
        """Map RTO or geography to Tata AIG territory column name."""
        if policy.territory:
            name = policy.territory.strip().upper()
            if name in _TERRITORY_COLS:
                return name, []
            return None, [f"Tata AIG: territory '{policy.territory}' is not a Pvtcar territory column."]
        rto = (policy.rto or "").lower().strip()
        geo = (policy.geography or "").lower().strip()

        # Only accept an explicitly supplied territory name.  The workbook does not
        # provide an RTO-to-territory table, so city/RTO substring guesses are unsafe.
        for name in _TERRITORY_COLS:
            if name.lower() == rto or name.lower() == geo:
                return name, []

        for alias, territory in _TERRITORY_ALIASES.items():
            if rto == alias or geo == alias:
                return territory, []

        if not rto and not geo:
            return None, [
                "RTO or geography is required for Tata AIG territory lookup."
            ]
        return None, [
            f"Tata AIG: RTO '{policy.rto}' and geography '{policy.geography}' "
            "are not an exact Pvtcar territory column. The workbook does not contain a Pvtcar-specific RTO-to-territory mapping table. "
            "Vaatun must supply the RTO cluster mapping to resolve this."
        ]

    def _resolve_fuel(self, policy: PolicyInput) -> tuple[str, list[str]]:
        fuel = (policy.fuel or "").lower().strip()
        if not fuel:
            return "", ["Fuel type is required for Tata AIG lookup; it will not be defaulted."]
        if fuel == "diesel":
            return "Diesel", []
        if fuel in {"cng", "lpg", "bifuel"}:
            return "CNG", []
        if fuel in {"electric", "ev"}:
            return "Electric", []
        return "Other Than Diesel", []

    def _product_to_section(self, product: str) -> str:
        mapping = {"Package": "Package", "SAOD": "SAOD", "SATP": "SATP"}
        return mapping.get(product, product)

    def _map_business_type(self, policy: PolicyInput) -> tuple[str | None, list[str]]:
        bt = (policy.business_type or "").lower().strip()
        if "rollover" in bt:
            return "Rollover", []
        if "renewal" in bt:
            return "Renewal", []
        if "new" in bt or "brand new" in bt:
            return "Brand New", []
        return None, ["Business type is required for Tata AIG lookup; it will not be defaulted to Brand New."]

    def _map_ncb(self, policy: PolicyInput, product: str) -> tuple[str | None, list[str]]:
        if product == "SATP":
            return "All", []
        ncb_state = (policy.ncb_state or "").strip()
        if ncb_state.upper() == "NCB":
            return "Yes", []
        if ncb_state.upper() == "NON-NCB":
            return "No", []
        if policy.ncb_percent is not None:
            return ("Yes" if policy.ncb_percent > 0 else "No"), []
        return None, ["NCB state is required for Tata AIG Package/SAOD lookup; it will not be defaulted."]

    _TP_ONLY_COVERS = ("pa cover", "personal accident", "legal liability", "third party", "third-party",
                       "tp for", "imt 25", "cng / lpg kit tp", "bi-fuel kit")

    def _add_on_flag(self, policy: PolicyInput) -> str | None:
        """'Yes' when an own-damage add-on cover was bought, 'No' when none; None if unknown."""
        if policy.add_ons is None:
            return None
        od_add_ons = [a for a in policy.add_ons
                      if not any(term in a.casefold() for term in self._TP_ONLY_COVERS)]
        return "Yes" if od_add_ons else "No"

    def _resolve_vehicle_type(self, policy: PolicyInput) -> tuple[str | None, str | None, list[str]]:
        """Resolve vehicle type (HE/UHE vs Other than HE/UHE) and segment from policy."""
        if policy.vehicle_segment:
            return None, policy.vehicle_segment, []
        return None, None, [
            "Vehicle segment is required for Tata AIG lookup. The supplied workbook does not provide a make/model-to-segment mapping, so it will not be inferred."
        ]
