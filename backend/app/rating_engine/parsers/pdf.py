from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pymupdf


def parse_pdf(path: str | Path,
              page_numbers: set[int] | None = None) -> dict[str, Any]:
    """Extract page text and table cells from a selectable-text PDF.

    OCR is not performed here.  Image-only pages are returned with an empty
    ``text`` string and ``image_only=True`` so callers can decide how to handle
    them (e.g. pass the raw PDF bytes to Gemini for extraction).
    """
    file = Path(path)
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    pages: list[dict[str, Any]] = []
    with pymupdf.open(file) as document:
        page_count = len(document)
        for page_number, page in enumerate(document, 1):
            if page_numbers is not None and page_number not in page_numbers:
                continue
            page_text = page.get_text("text")
            image_only = not page_text.strip() and bool(page.get_images())
            tables = []
            for table_number, table in enumerate(page.find_tables().tables, 1):
                tables.append({
                    "table_number": table_number,
                    "row_count": table.row_count,
                    "column_count": table.col_count,
                    "rows": [
                        {"row_number": row_number, "cells": row}
                        for row_number, row in enumerate(table.extract(), 1)
                    ],
                })
            pages.append({
                "page_number": page_number,
                "text": page_text,
                "tables": tables,
                "image_only": image_only,
                # Legacy fields kept for schema compatibility; always empty now.
                "ocr_used": False,
                "ocr_lines": [],
            })
    return {
        "document_name": file.name,
        "sha256": digest,
        "pages": pages,
        "page_count": page_count,
        "ocr_pages_limited": False,
    }
