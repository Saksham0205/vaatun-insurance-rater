from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import pymupdf

logger = logging.getLogger("vaatun.ocr")

_OCR_ENGINE: Any = None
_OCR_UNAVAILABLE = False
_OCR_CACHE = Path(tempfile.gettempdir()) / "vaatun-policy-ocr-cache"
# Read-only OCR output committed with the app for the sample policies, produced
# by this same engine and settings. It keys on the PDF's SHA-256, so it only ever
# matches those exact files; anything else is OCR'd live. Running OCR peaks at
# ~430-460 MB, close to the 512 MB instance limit, so known files skip it.
_BUNDLED_OCR_CACHE = Path(__file__).resolve().parents[3] / "ocr_cache"


def _disable_ort_mem_pattern() -> None:
    """Turn off onnxruntime's memory-pattern planning for RapidOCR sessions.

    The plan caches buffers per input shape; every new page size added to the
    peak (+355 MB per page vs +255 MB without it) with identical OCR output.
    RapidOCR 1.4.x exposes no option for this, so wrap its session-options hook.
    """
    try:
        from rapidocr_onnxruntime.utils import infer_engine
    except Exception:  # pragma: no cover - depends on install
        return
    original = infer_engine.OrtInferSession._init_sess_opts
    if getattr(original, "_vaatun_patched", False):
        return

    def init_sess_opts(config):
        options = original(config)
        options.enable_mem_pattern = False
        return options

    init_sess_opts._vaatun_patched = True
    infer_engine.OrtInferSession._init_sess_opts = staticmethod(init_sess_opts)


def _get_ocr_engine():
    """Lazily load RapidOCR; return None when it is not installed."""
    global _OCR_ENGINE, _OCR_UNAVAILABLE
    if _OCR_ENGINE is None and not _OCR_UNAVAILABLE:
        try:
            _disable_ort_mem_pattern()
            from rapidocr_onnxruntime import RapidOCR
            # Each onnxruntime thread keeps its own scratch buffers; small instances
            # have 1-2 vCPUs, so more threads only add memory.
            threads = int(os.getenv("LOCAL_OCR_THREADS", "2"))
            _OCR_ENGINE = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1)
        except Exception as exc:  # pragma: no cover - depends on install
            logger.warning("Local OCR unavailable (%s); scanned pages cannot be read", exc)
            _OCR_UNAVAILABLE = True
    return _OCR_ENGINE


def _ocr_page(page: Any, digest: str, page_number: int) -> list[dict[str, Any]] | None:
    """OCR one image-only page locally (no API quota). Results are cached per PDF hash."""
    name = f"{digest}-{page_number}.json"
    cache_file = _OCR_CACHE / name
    for cached in (_BUNDLED_OCR_CACHE / name, cache_file):
        if cached.is_file():
            try:
                return json.loads(cached.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    engine = _get_ocr_engine()
    if engine is None:
        return None
    import numpy as np

    pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    result, _ = engine(image)
    del image, pix
    pymupdf.TOOLS.store_shrink(100)
    lines: list[dict[str, Any]] = []
    for box, text, confidence in result or []:
        lines.append({"text": text, "confidence": float(confidence),
                      "x": round(min(p[0] for p in box) / 2, 2),
                      "y": round(min(p[1] for p in box) / 2, 2)})
    lines.sort(key=lambda item: (item["y"], item["x"]))
    try:
        _OCR_CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(lines), encoding="utf-8")
    except OSError:
        pass
    return lines


def parse_pdf(path: str | Path,
              page_numbers: set[int] | None = None,
              ocr: bool | None = None,
              max_ocr_pages: int | None = None) -> dict[str, Any]:
    """Extract page text and table cells.

    Image-only (scanned) pages are OCR'd locally with RapidOCR, up to
    ``max_ocr_pages`` (the schedule pages; later pages are policy wordings).
    Pages that still have no text keep ``image_only=True``.
    """
    if ocr is None:
        ocr = os.getenv("LOCAL_OCR_ENABLED", "true").casefold() != "false"
    if max_ocr_pages is None:
        max_ocr_pages = int(os.getenv("LOCAL_OCR_MAX_PAGES", "8"))
    try:
        return _parse_pdf(Path(path), page_numbers, ocr, max_ocr_pages)
    finally:
        # MuPDF keeps decoded fonts/images/display lists in a global store that is
        # never handed back on its own; it grew RSS by ~50-100 MB per policy and
        # pushed the service past its memory limit.
        pymupdf.TOOLS.store_shrink(100)


def _parse_pdf(file: Path, page_numbers: set[int] | None, ocr: bool,
               max_ocr_pages: int) -> dict[str, Any]:
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    pages: list[dict[str, Any]] = []
    ocr_count = 0
    with pymupdf.open(file) as document:
        page_count = len(document)
        for page_number, page in enumerate(document, 1):
            if page_numbers is not None and page_number not in page_numbers:
                continue
            page_text = page.get_text("text")
            has_text_layer = bool(page_text.strip())
            image_only = not has_text_layer and bool(page.get_images())
            ocr_lines: list[dict[str, Any]] = []
            ocr_used = False
            if image_only and ocr and ocr_count < max_ocr_pages:
                lines = _ocr_page(page, digest, page_number)
                ocr_count += 1
                if lines:
                    ocr_lines = lines
                    page_text = "\n".join(line["text"] for line in lines)
                    ocr_used = True
                    image_only = False
            tables = []
            # A page without a text layer has no table cells to extract, and
            # find_tables() on a scanned page still costs ~130 MB transiently.
            found = page.find_tables().tables if has_text_layer else []
            for table_number, table in enumerate(found, 1):
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
                "ocr_used": ocr_used,
                "ocr_lines": ocr_lines,
            })
    return {
        "document_name": file.name,
        "sha256": digest,
        "pages": pages,
        "page_count": page_count,
        # Kept for stored-result compatibility; the OCR page cap covers the schedule pages.
        "ocr_pages_limited": False,
    }
