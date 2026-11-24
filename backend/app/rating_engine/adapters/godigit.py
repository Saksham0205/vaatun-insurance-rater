"""Go Digit 4W rate-card adapter.

Source: Large Insurance Brokers Mar'26 - Shared.xlsx

  - 4W SATP: RTO code -> 4WTP cluster, fuel/CC segment and age band -> "Max CD2".
    Max CD2 is read as the payout rate in decimal form (0.295 = 29.5%), as on the
    New Business 1+3 sheet, applied to the TP premium and disclosed as an assumption.
  - 4W New Business 1+3: RTO code -> 4W Package cluster, make group -> CD2 rate on the
    OD premium (new business only).
  - Renault appears in two make groups, so a Renault make stays ambiguous.
  - The workbook has no 4W SAOD grid, so SAOD is unsupported.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl

from ..exceptions import exception_decision
from ..models import (Component, ComponentDecision, DecisionStatus,
                      NormalizedRateRule, PolicyInput, SourceRef, SourceValue)

GODIGIT_FILENAME = "Large Insurance Brokers Mar'26 - Shared.xlsx"
GODIGIT_CARD_VERSION = "March 2026"

# Column indices in 4W RTO sheet (0-indexed within row tuple, skipping first None col)
# Row header: (None, 'RTO Code', '4WTP', '4W Package', '4WSAOD', 'PLR Cluster')
_RTO_COL_TP = 2       # 4WTP cluster
_RTO_COL_PKG = 3      # 4W Package cluster
_RTO_COL_SAOD = 4     # 4WSAOD cluster

# Make-group column mapping in 4W New Business 1+3 (0-indexed including first None col)
# Row header: (None, 'Cluster', 'Tata', 'Kia', 'Mahindra', 'Hyundai', 'Toyota',
#              'HEV-…,Renault,…', 'Maruti,MG,…,Renault,Others', None)
_NB_CLUSTER_COL = 0
_NB_COLS = {
    "tata": 1,
    "kia": 2,
    "mahindra": 3,
    "hyundai": 4,
    "toyota": 5,
    "hev": 6,       # HEV group: Mercedes Benz, Ford, BMW, Jeep, Ferrari, Bentley,
                    # Rolls Royce, Chevrolet, Datsun, Nissan, Renault, Jaguar,
                    # Land Rover, BYD, Citrone, Tesla, Audi, Volvo, Porsche
    "others": 7,    # Maruti, MG, Skoda, Volks, Honda, Renault, Others
}

# Makes that appear ONLY in one column (no Renault conflict)
_MAKE_TO_GROUP: dict[str, str] = {
    "tata": "tata",
    "kia": "kia",
    "mahindra": "mahindra",
    "hyundai": "hyundai",
    "toyota": "toyota",
    # HEV group (not exhaustive – just the unambiguous ones)
    "mercedes benz": "hev", "mercedes-benz": "hev",
    "ford": "hev",
    "bmw": "hev",
    "jeep": "hev",
    "ferrari": "hev",
    "bentley": "hev",
    "rolls royce": "hev",
    "chevrolet": "hev",
    "datsun": "hev",
    "nissan": "hev",
    "jaguar": "hev",
    "land rover": "hev",
    "byd": "hev",
    "citroen": "hev",
    "tesla": "hev",
    "audi": "hev",
    "volvo": "hev",
    "porsche": "hev",
    # others group (non-conflicting)
    "maruti": "others", "maruti suzuki": "others",
    "mg": "others",
    "skoda": "others",
    "volkswagen": "others", "volks": "others",
    "honda": "others",
}
# Renault appears in both "hev" and "others" → conflict
_RENAULT_CONFLICT = True


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


class GoDigitAdapter:
    """Go Digit 4W private-car rate adapter (4W SATP and New Business 1+3)."""
    insurer_key = "godigit"
    card_version = GODIGIT_CARD_VERSION

    def __init__(self, rate_card_root: str | Path):
        self.root = Path(rate_card_root)
        self._path = self.root / "godigit" / "march-2026" / GODIGIT_FILENAME

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

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
            msg = f"Go Digit source file missing: {GODIGIT_FILENAME}"
            if od_applicable:
                od.issues.append(msg)
            if tp_applicable:
                tp.issues.append(msg)
            return od, tp

        file_sha = _sha256(self._path)

        if product == "SATP":
            # SATP: TP commission from 4W SATP sheet
            od = ComponentDecision(Component.OD, DecisionStatus.NOT_APPLICABLE, False)
            tp = self._rate_satp(policy, file_sha)
            return od, tp

        if product in ("Package", "SAOD"):
            # New Business 1+3 (Package)
            od, tp = self._rate_package_or_saod(policy, product, file_sha)
            return od, tp

        od.issues.append(f"Go Digit: unrecognised product '{product}'.")
        tp.issues.append(f"Go Digit: unrecognised product '{product}'.")
        return od, tp

    # ------------------------------------------------------------------ #
    # SATP                                                                #
    # ------------------------------------------------------------------ #

    def _rate_satp(self, policy: PolicyInput, file_sha: str) -> ComponentDecision:
        tp = ComponentDecision(Component.TP, DecisionStatus.AMBIGUOUS, True)
        tp.evidence = [SourceRef(GODIGIT_FILENAME, file_sha, sheet="4W SATP", role="rate_card_source")]

        # The 4W RTO sheet is keyed by RTO code; a printed RTO name will not match it.
        rto = policy.rto_code or policy.rto
        if not rto:
            tp.issues.append("RTO is required for Go Digit 4WTP cluster mapping.")
            return tp

        # Map RTO → 4WTP cluster
        cluster, rto_evidence, rto_issues = self._resolve_rto_cluster(rto, file_sha, "4WTP")
        if rto_issues:
            tp.issues.extend(rto_issues)
            return tp

        # Fuel and engine CC
        fuel_group, engine_cc = self._fuel_cc_segment(policy)
        if fuel_group is None:
            tp.issues.append("Fuel type is required for Go Digit 4W SATP segment lookup.")
            return tp

        # Vehicle age
        vehicle_age = policy.vehicle_age_years
        if vehicle_age is None:
            tp.issues.append("Vehicle age is required for Go Digit 4W SATP age-band lookup.")
            return tp

        age_band = "<10" if vehicle_age < 10 else ">10"
        segment = self._satp_segment(fuel_group, engine_cc)

        # Look up in 4W SATP sheet
        wb = openpyxl.load_workbook(self._path, data_only=True, read_only=True)
        try:
            ws = wb["4W SATP"]
            matched_rows: list[tuple[int, Any, Any]] = []
            for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                row_cluster = str(row[1] or "").strip() if row[1] is not None else ""
                row_segment = str(row[2] or "").strip() if row[2] is not None else ""
                row_age = str(row[3] or "").strip() if row[3] is not None else ""
                raw_cd2 = row[4]
                note = row[5]

                cluster_match = row_cluster.upper() == cluster.upper()
                segment_match = self._satp_segment_matches(row_segment, segment, fuel_group, engine_cc)
                age_match = row_age.upper() == "ALL" or row_age == age_band

                if cluster_match and segment_match and age_match:
                    matched_rows.append((row_idx, raw_cd2, note))
        finally:
            wb.close()

        source_ref = SourceRef(GODIGIT_FILENAME, file_sha, sheet="4W SATP", role="rate_card_source")
        tp.evidence = [*rto_evidence, source_ref]
        tp.selected_conditions = {
            "cluster": cluster, "segment": segment, "age_band": age_band, "rto": rto
        }

        if not matched_rows:
            tp.issues.append(
                f"No Go Digit 4W SATP row matches cluster={cluster!r}, segment={segment!r}, age={age_band!r}."
            )
            return tp

        if len(matched_rows) > 1:
            tp.issues.append(
                f"Multiple Go Digit 4W SATP rows match cluster={cluster!r}, segment={segment!r}, age={age_band!r} "
                f"({len(matched_rows)} rows)."
            )
            return tp

        row_idx, raw_cd2, note = matched_rows[0]
        cell_ref = SourceRef(GODIGIT_FILENAME, file_sha, sheet="4W SATP", cell=f"E{row_idx}", role="rate_cell")
        tp.evidence.append(cell_ref)

        # Explicit-decline cluster handling
        if cluster.upper() == "ALL_INDIA_DECLINE":
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append(
                "Go Digit 4W SATP: cluster is All_India_Decline. This risk is explicitly declined."
            )
            return tp

        # "Max CD2" is the maximum intermediary payout (CD2) for the cell. The
        # New Business 1+3 sheet in the same workbook states its CD2 values as
        # payout rates in decimal form, so SATP Max CD2 is read the same way and
        # applied to the TP premium. This reading is disclosed on the decision.
        try:
            rate = (Decimal(str(raw_cd2)) * Decimal(100)).quantize(Decimal("0.01")).normalize()
        except Exception:
            tp.issues.append(f"Go Digit 4W SATP: Max CD2 cell E{row_idx} is not numeric ({raw_cd2!r}).")
            return tp
        tp.rate_percent = rate
        tp.rate_basis = "TP premium"
        tp.status = DecisionStatus.RESOLVED
        tp.issues.append("Assumption: 'Max CD2' is the payout rate (decimal form, e.g. 0.46 = 46%), "
                         "consistent with the CD2 rates on the New Business 1+3 sheet.")
        if policy.tp_premium is not None:
            tp.premium_basis = policy.tp_premium
            tp.commission_amount = (policy.tp_premium * rate / Decimal(100)).quantize(Decimal("0.01"))
            tp.calculation = f"TP premium {policy.tp_premium} × {rate}% = {tp.commission_amount}"
        else:
            tp.issues.append("Commission amount not calculated because the TP premium is missing.")
        if note:
            tp.issues.append(f"Source note: {note}")
        return tp

    # ------------------------------------------------------------------ #
    # Package / SAOD                                                      #
    # ------------------------------------------------------------------ #

    def _rate_package_or_saod(self, policy: PolicyInput, product: str,
                              file_sha: str) -> tuple[ComponentDecision, ComponentDecision]:
        od = ComponentDecision(Component.OD,
                               DecisionStatus.NOT_APPLICABLE if product == "SATP" else DecisionStatus.AMBIGUOUS,
                               product != "SATP")
        tp = ComponentDecision(Component.TP,
                               DecisionStatus.NOT_APPLICABLE if product == "SAOD" else DecisionStatus.AMBIGUOUS,
                               product != "SAOD")

        # For Package the grid is "4W New Business 1+3" (new business only)
        # SAOD: same cluster mapping but sheet not present for OD renewal — flag as unsupported
        # The source only provides "New Business 1+3"; we implement that only.
        if product == "SAOD":
            od.issues.append(
                "Go Digit: the supplied workbook does not contain a dedicated 4W SAOD old-business "
                "commission grid. Only 4W SATP and 4W New Business 1+3 sheets are present."
            )
            od.status = DecisionStatus.UNSUPPORTED
            # TP not applicable for SAOD
            return od, tp

        # Package (new business)
        business = (policy.business_type or "").casefold().strip()
        if business not in {"new", "new business", "brand new"}:
            od.issues.append(
                "Go Digit 4W New Business 1+3 applies only to explicitly identified new business; "
                "the policy business type is missing or outside that scope."
            )
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: no separate TP rate is supplied by the New Business 1+3 grid.")
            return od, tp
        # The 4W RTO sheet is keyed by RTO code; a printed RTO name will not match it.
        rto = policy.rto_code or policy.rto
        if not rto:
            od.issues.append("RTO is required for Go Digit 4W Package cluster mapping.")
            tp.issues.append("Go Digit TP commission not provided in New Business 1+3 grid.")
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: supplied 4W New Business 1+3 sheet contains only OD (CD2) rate; no TP rate column.")
            return od, tp

        cluster, rto_evidence, rto_issues = self._resolve_rto_cluster(rto, file_sha, "4W Package")
        if rto_issues:
            od.issues.extend(rto_issues)
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: supplied 4W New Business 1+3 sheet contains only OD (CD2) rate; no TP rate column.")
            return od, tp

        make = (policy.make or "").strip().lower()
        if not make:
            od.issues.append("Vehicle make is required for Go Digit 4W New Business 1+3 make-group lookup.")
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: supplied 4W New Business 1+3 sheet contains only OD (CD2) rate; no TP rate column.")
            return od, tp

        # Resolve make group
        group_col, group_issues = self._resolve_make_group(make)
        if group_issues:
            od.status = DecisionStatus.AMBIGUOUS
            od.issues.extend(group_issues)
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: supplied 4W New Business 1+3 sheet contains only OD (CD2) rate; no TP rate column.")
            return od, tp

        # Look up cluster row in 4W New Business 1+3
        wb = openpyxl.load_workbook(self._path, data_only=True, read_only=True)
        try:
            ws = wb["4W New Business 1+3"]
            matched: list[tuple[int, Any]] = []
            for row_idx, row in enumerate(ws.iter_rows(min_row=3, values_only=True), start=3):
                # Row: (cluster, Tata, Kia, Mahindra, Hyundai, Toyota, HEV, Others, 3+3)
                if row[0] is None:
                    continue
                row_cluster = str(row[0]).strip()
                if row_cluster.upper() == cluster.upper():
                    rate_raw = row[group_col] if group_col < len(row) else None
                    matched.append((row_idx, rate_raw))
        finally:
            wb.close()

        source_ref = SourceRef(GODIGIT_FILENAME, file_sha, sheet="4W New Business 1+3", role="rate_card_source")
        od.evidence = [*rto_evidence, source_ref]
        od.selected_conditions = {"cluster": cluster, "make_group": list(_NB_COLS.keys())[group_col - 1], "rto": rto}

        if not matched:
            od.issues.append(
                f"No Go Digit 4W New Business 1+3 row found for cluster={cluster!r}."
            )
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: supplied 4W New Business 1+3 sheet contains only OD (CD2) rate; no TP rate column.")
            return od, tp

        if len(matched) > 1:
            od.issues.append(
                f"Multiple rows match cluster={cluster!r} in 4W New Business 1+3 ({len(matched)} rows)."
            )
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: supplied 4W New Business 1+3 sheet contains only OD (CD2) rate; no TP rate column.")
            return od, tp

        row_idx, rate_raw = matched[0]
        cell_col_letter = chr(ord("A") + group_col)  # Excel column letter for the evidence reference
        cell_ref = SourceRef(
            GODIGIT_FILENAME, file_sha,
            sheet="4W New Business 1+3", cell=f"{cell_col_letter}{row_idx}", role="rate_cell"
        )
        od.evidence.append(cell_ref)

        if rate_raw is None:
            od.status = DecisionStatus.AMBIGUOUS
            od.issues.append("Go Digit 4W New Business 1+3: source cell is empty (not zero).")
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: supplied 4W New Business 1+3 sheet contains only OD (CD2) rate; no TP rate column.")
            return od, tp

        try:
            rate_decimal = Decimal(str(rate_raw))
        except Exception:
            od.status = DecisionStatus.AMBIGUOUS
            od.issues.append(f"Go Digit 4W New Business 1+3: could not parse rate value {rate_raw!r}.")
            tp.status = DecisionStatus.UNSUPPORTED
            tp.issues.append("Go Digit: supplied 4W New Business 1+3 sheet contains only OD (CD2) rate; no TP rate column.")
            return od, tp

        # Rate is in decimal (0.195 = 19.5%)
        rate_pct = rate_decimal * Decimal("100")

        # Build rule
        rule = NormalizedRateRule(
            insurer_key="godigit",
            card_version=GODIGIT_CARD_VERSION,
            conditions=od.selected_conditions,
            component=Component.OD,
            rate_percent=rate_pct,
            rate_basis="OD premium",
            source_value=SourceValue(cell_ref, rate_raw,
                                     note="Decimal value from 4W New Business 1+3; multiplied ×100 for percentage."),
        )
        status, issue = exception_decision(rule)
        od.status = status
        od.rate_percent = rule.rate_percent
        od.rate_basis = rule.rate_basis
        if policy.od_premium is not None:
            od.premium_basis = policy.od_premium
            od.commission_amount = (
                policy.od_premium * rate_pct / Decimal("100")
            ).quantize(Decimal("0.01"))
            od.calculation = (
                f"OD premium {policy.od_premium} × {rate_pct}% = {od.commission_amount}"
            )
        if issue:
            od.issues.append(issue)

        # TP: not in this grid
        tp.status = DecisionStatus.UNSUPPORTED
        tp.issues.append(
            "Go Digit: the supplied 4W New Business 1+3 workbook sheet contains only CD2 (OD) rate. "
            "No separate TP commission column is present."
        )
        return od, tp

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _resolve_rto_cluster(self, rto: str, file_sha: str,
                              product_col_name: str) -> tuple[str | None, list[SourceRef], list[str]]:
        """Map RTO code to cluster using 4W RTO sheet, product-specific column."""
        col_index = {
            "4WTP": _RTO_COL_TP,
            "4W Package": _RTO_COL_PKG,
            "4WSAOD": _RTO_COL_SAOD,
        }.get(product_col_name, _RTO_COL_PKG)

        wb = openpyxl.load_workbook(self._path, data_only=True, read_only=True)
        try:
            ws = wb["4W  RTO"]
            rto_key = rto.upper().replace(" ", "").replace("-", "")
            for row in ws.iter_rows(min_row=3, values_only=True):
                if row[1] is None:
                    continue
                code = str(row[1]).strip().upper().replace(" ", "").replace("-", "")
                if code == rto_key:
                    cluster = str(row[col_index]).strip() if row[col_index] is not None else None
                    if cluster is None:
                        return None, [], [
                            f"Go Digit 4W RTO: RTO {rto!r} found but cluster column '{product_col_name}' is empty."
                        ]
                    rto_ref = SourceRef(GODIGIT_FILENAME, file_sha, sheet="4W  RTO",
                                        cell=f"B{ws.min_row}", role="rto_mapping")
                    return cluster, [rto_ref], []
        finally:
            wb.close()

        return None, [], [f"Go Digit 4W RTO: no row found for RTO code '{rto}'."]

    def _fuel_cc_segment(self, policy: PolicyInput) -> tuple[str | None, int | None]:
        fuel = (policy.fuel or "").lower().strip()
        if not fuel:
            return None, policy.engine_cc
        if fuel in {"petrol", "hybrid", "electric", "ev"}:
            return "petrol", policy.engine_cc
        if fuel in {"diesel"}:
            return "diesel", policy.engine_cc
        if fuel in {"cng", "lpg", "bifuel"}:
            return "cng", policy.engine_cc
        return fuel, policy.engine_cc

    def _satp_segment(self, fuel_group: str, engine_cc: int | None) -> str:
        """Map fuel + CC to 4W SATP segment notation (e.g. 'Petrol<1000')."""
        if fuel_group == "petrol":
            if engine_cc is None:
                return "Petrol"  # ambiguous – will not match if CC-specific rows exist
            return "Petrol<1000" if engine_cc < 1000 else "Petrol>1000"
        if fuel_group == "diesel":
            if engine_cc is None:
                return "Diesel"
            return "Diesel<1500" if engine_cc < 1500 else "Diesel>1500"
        if fuel_group == "cng":
            if engine_cc is None:
                return "CNG"
            return "CNG<1000" if engine_cc < 1000 else "CNG>1000"
        return fuel_group

    def _satp_segment_matches(self, row_segment: str, segment: str,
                              fuel_group: str, engine_cc: int | None) -> bool:
        """Check whether a source segment string matches the policy segment."""
        rs = row_segment.strip().replace(" ", "")
        ps = segment.strip().replace(" ", "")
        return rs.upper() == ps.upper()

    def _resolve_make_group(self, make_lower: str) -> tuple[int, list[str]]:
        """Return the column index (0-indexed within row tuple) and any issues."""
        # Renault conflict
        if "renault" in make_lower:
            return -1, [
                "Go Digit 4W New Business 1+3: 'Renault' appears in both "
                "make-group columns ('HEV-Mercedes Benz, Ford … Renault' and "
                "'Maruti, MG, Skoda … Renault, Others'). "
                "The source does not establish which column takes precedence. "
                "Commission cannot be resolved without Vaatun clarification."
            ]
        for key, group in _MAKE_TO_GROUP.items():
            if key in make_lower or make_lower in key:
                return _NB_COLS[group], []
        return -1, [
            f"Go Digit 4W New Business 1+3: make '{make_lower}' is not explicitly listed in a source make group. "
            "It will not be inferred as 'Others' without Vaatun confirmation."
        ]
