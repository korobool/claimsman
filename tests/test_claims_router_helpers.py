"""Unit tests for the pure helper functions inside
``apps/web/routers/claims.py`` — bbox overlap, line sort key, and
the pipeline-stage compute. These don't touch the DB."""
from unittest.mock import MagicMock

from apps.web.routers.claims import (
    _bbox_overlaps,
    _compute_doc_stage,
    _compute_stage,
    _line_sort_key,
)


# --- _bbox_overlaps -----------------------------------------------------


def test_bbox_overlaps_no_intersection_returns_false() -> None:
    assert _bbox_overlaps([0, 0, 10, 10], [20, 20, 30, 30], 0.30) is False


def test_bbox_overlaps_small_existing_fully_inside_large_new() -> None:
    # existing is 10x10, fully inside a 100x100 new box. 100% of
    # existing is overlapped → removed.
    assert _bbox_overlaps([20, 20, 30, 30], [0, 0, 100, 100], 0.30) is True


def test_bbox_overlaps_large_existing_partially_inside_small_new() -> None:
    # existing is 100x100, new is 10x10 inside it. Only 1% of existing
    # overlaps → below the 30% threshold → NOT removed.
    assert _bbox_overlaps([0, 0, 100, 100], [20, 20, 30, 30], 0.30) is False


def test_bbox_overlaps_exact_threshold_not_removed() -> None:
    # Equal-sized boxes with 30% area overlap would be right at the
    # threshold. Use a simple case: existing 10x10, new 10x10 but
    # shifted so 3x10 overlaps → 30% of existing. Should NOT trigger
    # (requires strictly greater than).
    existing = [0, 0, 10, 10]
    new = [7, 0, 17, 10]  # intersection is (7..10, 0..10) = 3x10 = 30
    assert _bbox_overlaps(existing, new, 0.30) is False  # exactly 30%, not > 30%


def test_bbox_overlaps_zero_area_safe() -> None:
    assert _bbox_overlaps([5, 5, 5, 5], [0, 0, 10, 10], 0.30) is False


# --- _line_sort_key (top-to-bottom, left-to-right) ---------------------


def test_line_sort_key_orders_top_to_bottom_then_left_to_right() -> None:
    lines = [
        {"bbox": [100, 10, 200, 20], "text": "top-right"},
        {"bbox": [0, 10, 80, 20], "text": "top-left"},
        {"bbox": [0, 50, 80, 60], "text": "bottom-left"},
    ]
    lines.sort(key=_line_sort_key)
    assert [l["text"] for l in lines] == ["top-left", "top-right", "bottom-left"]


def test_line_sort_key_missing_bbox_goes_first() -> None:
    lines = [
        {"bbox": [0, 50, 80, 60], "text": "middle"},
        {"text": "no-bbox"},
        {"bbox": [0, 10, 80, 20], "text": "top"},
    ]
    lines.sort(key=_line_sort_key)
    # the 'no-bbox' entry sorts with key (0.0, 0.0) → first
    assert lines[0]["text"] == "no-bbox"


# --- _compute_stage and _compute_doc_stage -----------------------------


def _fake_claim(status: str, documents: list, findings: list | None = None) -> MagicMock:
    claim = MagicMock()
    claim.status = MagicMock()
    claim.status.value = status
    claim.documents = documents
    claim.findings = findings or []
    return claim


def _fake_page(*, image: bool, ocr_text: str | None = None, classification: str | None = None, text_layer_used: bool = False):
    page = MagicMock()
    page.image_path = "/tmp/x.png" if image else None
    page.ocr_text = ocr_text
    page.classification = classification
    page.text_layer_used = text_layer_used
    return page


def _fake_doc(pages: list, extracted_fields: list | None = None):
    d = MagicMock()
    d.pages = pages
    d.extracted_fields = extracted_fields or []
    return d


def test_compute_stage_ready_for_review_is_ready() -> None:
    claim = _fake_claim("ready_for_review", documents=[])
    res = _compute_stage(claim, proposed=None)
    assert res["stage"] == "ready"
    assert res["active"] is False
    assert res["progress"] == 1.0


def test_compute_stage_empty_claim_is_ingest() -> None:
    claim = _fake_claim("processing", documents=[])
    res = _compute_stage(claim, proposed=None)
    assert res["stage"] == "ingest"


def test_compute_stage_ocr_counts_pages() -> None:
    pages = [
        _fake_page(image=True, ocr_text="done"),
        _fake_page(image=True, ocr_text=None),
        _fake_page(image=True, ocr_text=None),
    ]
    doc = _fake_doc(pages)
    claim = _fake_claim("processing", documents=[doc])
    res = _compute_stage(claim, proposed=None)
    assert res["stage"] == "ocr"
    assert "pages" in res["totals"]
    assert res["totals"]["pages_ocr"] == 1
    assert res["totals"]["pages_with_image"] == 3


def test_compute_stage_classify_when_ocr_done() -> None:
    pages = [
        _fake_page(image=True, ocr_text="a"),
        _fake_page(image=True, ocr_text="b"),
    ]
    doc = _fake_doc(pages)
    claim = _fake_claim("processing", documents=[doc])
    res = _compute_stage(claim, proposed=None)
    assert res["stage"] == "classify"


def test_compute_doc_stage_ready_when_fully_processed() -> None:
    pages = [_fake_page(image=True, ocr_text="hi", classification="receipt")]
    doc = _fake_doc(pages, extracted_fields=["stub"])
    assert _compute_doc_stage(doc) == "ready"


def test_compute_doc_stage_ocr_when_pages_unprocessed() -> None:
    pages = [_fake_page(image=True, ocr_text=None)]
    doc = _fake_doc(pages)
    assert _compute_doc_stage(doc) == "ocr"
