import pytest


@pytest.fixture(autouse=True)
def _local_ocr_default(request, monkeypatch):
    """Tests built on synthetic image-only PDFs opt out of OCR with ``no_ocr``."""
    if request.node.get_closest_marker("no_ocr"):
        monkeypatch.setenv("LOCAL_OCR_ENABLED", "false")


def pytest_configure(config):
    config.addinivalue_line("markers", "no_ocr: run without local OCR")
