"""The committed OCR cache must cover the sample policies so the server never runs OCR on them."""
from pathlib import Path

import pytest

from app.rating_engine.parsers import pdf as pdf_parser


ROOT = Path(__file__).resolve().parents[2]
POLICIES = sorted((ROOT / "sample-policies").glob("*.pdf"))


@pytest.mark.parametrize("policy", POLICIES, ids=lambda p: p.name)
def test_sample_policy_is_parsed_from_bundled_ocr_without_loading_engine(policy, tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_parser, "_OCR_CACHE", tmp_path)  # no live-OCR cache to fall back on
    monkeypatch.setattr(pdf_parser, "_OCR_ENGINE", None)

    def fail_engine():
        raise AssertionError(f"{policy.name}: a page is missing from backend/ocr_cache; regenerate it")

    monkeypatch.setattr(pdf_parser, "_get_ocr_engine", fail_engine)

    parsed = pdf_parser.parse_pdf(policy)

    assert any(page["ocr_used"] for page in parsed["pages"])
    assert not list(tmp_path.iterdir())
