from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ..models import SourceRef, SourceValue


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_workbook(path: str | Path, selected_sheets: set[str] | None = None) -> dict[str, Any]:
    """Extract source cells only; this parser assigns no insurance meaning."""
    file = Path(path)
    file_hash = _sha256(file)
    # Normal worksheets preserve comments and formula metadata; read_only cells do not expose comments.
    formulas_wb = load_workbook(file, data_only=False, read_only=False)
    cached_wb = load_workbook(file, data_only=True, read_only=False)
    sheets: list[dict[str, Any]] = []
    try:
        for ws in formulas_wb.worksheets:
            if selected_sheets is not None and ws.title not in selected_sheets:
                continue
            cached_ws = cached_wb[ws.title]
            cells: list[SourceValue] = []
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue
                    formula = cell.value if isinstance(cell.value, str) and cell.value.startswith("=") else None
                    cached = cached_ws[cell.coordinate].value if formula else None
                    cells.append(SourceValue(
                        ref=SourceRef(file.name, file_hash, ws.title, cell.coordinate, role="source_cell"),
                        original_value=cell.value,
                        formula=formula,
                        cached_value=cached,
                        note=cell.comment.text if cell.comment else None,
                    ))
            sheets.append({"name": ws.title, "max_row": ws.max_row, "max_column": ws.max_column,
                           "cells": cells})
    finally:
        formulas_wb.close()
        cached_wb.close()
    return {"workbook_name": file.name, "sha256": file_hash, "sheets": sheets}
