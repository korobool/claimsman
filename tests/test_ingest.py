"""Tests for ``packages/ingest`` — creates synthetic image and PDF
inputs and verifies that ingest_file produces the expected
IngestedDocument shape."""
import tempfile
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

from packages.ingest import SourceKind, ingest_file


def _make_png(tmp: Path, name: str = "sample.png", size: tuple[int, int] = (200, 100)) -> Path:
    img = Image.new("RGB", size, "white")
    path = tmp / name
    img.save(path)
    return path


def test_ingest_image_png() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = _make_png(tmp)
        out = tmp / "out"
        result = ingest_file(src, out, mime_hint="image/png")
        assert result.kind == SourceKind.IMAGE
        assert len(result.pages) == 1
        page = result.pages[0]
        assert page.image_path is not None
        assert page.image_path.exists()
        assert page.width == 200
        assert page.height == 100
        assert page.text_layer is None


def test_ingest_unsupported_extension_returns_unknown() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "weird.xyz"
        src.write_bytes(b"mystery")
        out = tmp / "out"
        result = ingest_file(src, out)
        assert result.kind == SourceKind.UNKNOWN
        assert result.pages == []


def test_ingest_pdf_with_embedded_text_layer() -> None:
    """Create a tiny PDF via PIL and verify ingest_file extracts an
    image for the page."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "sample.pdf"
        img = Image.new("RGB", (400, 600), "white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "HELLO WORLD", fill="black")
        img.save(src, "PDF", resolution=72)
        out = tmp / "out"
        result = ingest_file(src, out, mime_hint="application/pdf")
        assert result.kind in (SourceKind.PDF_SCANNED, SourceKind.PDF_TEXT_LAYER)
        assert len(result.pages) == 1
        page = result.pages[0]
        assert page.image_path is not None
        assert page.image_path.exists()
        assert page.width is not None and page.height is not None


def test_pypdfium2_is_available() -> None:
    # Sanity: the test dependency is importable.
    assert pdfium is not None
