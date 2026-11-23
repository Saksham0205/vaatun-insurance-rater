from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import pymupdf
import numpy as np

_OCR_ENGINE = None
_OCR_CACHE = Path(tempfile.gettempdir()) / "vaatun-policy-ocr-cache"


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def parse_pdf(path: str | Path, ocr_fallback: bool = True,
              page_numbers: set[int] | None = None,
              max_ocr_pages: int | None = None) -> dict[str, Any]:
    """Extract page text/table cells; OCR image-only pages without interpreting their meaning."""
    file = Path(path)
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    pages: list[dict[str, Any]] = []
    with pymupdf.open(file) as document:
        page_count = len(document)
        ocr_count = 0
        ocr_limit_hit = False
        for page_number, page in enumerate(document, 1):
            if page_numbers is not None and page_number not in page_numbers:
                continue
            page_text = page.get_text("text")
            ocr_lines = []
            ocr_used = False
            should_ocr = (max_ocr_pages is None or ocr_count < max_ocr_pages)
            if not page_text.strip() and ocr_fallback and page.get_images() and not should_ocr:
                ocr_limit_hit = True
            if not page_text.strip() and ocr_fallback and should_ocr and page.get_images():
                cache_file = _OCR_CACHE / f"{digest}-{page_number}.json"
                cached = None
                if cache_file.is_file():
                    try:
                        cached = json.loads(cache_file.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        cached = None
                if cached is not None:
                    ocr_lines = cached
                else:
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                    result, _ = _get_ocr_engine()(image)
                    if result:
                        for box, text, confidence in result:
                            x0 = min(point[0] for point in box) / 2
                            y0 = min(point[1] for point in box) / 2
                            ocr_lines.append({"text": text, "confidence": float(confidence),
                                              "x": round(x0, 2), "y": round(y0, 2)})
                        ocr_lines.sort(key=lambda item: (item["y"], item["x"]))
                    _OCR_CACHE.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(ocr_lines), encoding="utf-8")
                ocr_count += 1
                ocr_used = True
                if ocr_lines:
                    page_text = "\n".join(line["text"] for line in ocr_lines)
            tables = []
            for table_number, table in enumerate(page.find_tables().tables, 1):
                tables.append({"table_number": table_number, "row_count": table.row_count,
                               "column_count": table.col_count,
                               "rows": [{"row_number": row_number, "cells": row}
                                        for row_number, row in enumerate(table.extract(), 1)]})
            pages.append({"page_number": page_number, "text": page_text, "tables": tables,
                          "ocr_used": ocr_used, "ocr_lines": ocr_lines})
    return {"document_name": file.name, "sha256": digest, "pages": pages,
            "page_count": page_count, "ocr_pages_limited": ocr_limit_hit}
