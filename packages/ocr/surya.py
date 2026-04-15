"""Surya OCR wrapper.

Surya is the ONLY OCR engine used in Claimsman (spec §4.2, F-2.1).
This module lazy-loads Surya's detection + recognition models on first
use and keeps them in memory for the process lifetime.

Inputs are PIL images; output is a structured OcrResult with per-line
bounding boxes and confidence. The wrapper is deliberately tiny and
independent of any Claimsman application layer so it can be reused or
unit-tested in isolation.
"""
from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Optional

from PIL import Image


@dataclass
class OcrLine:
    text: str
    bbox: list[float]  # [x0, y0, x1, y1] in page pixels
    confidence: float
    polygon: Optional[list[list[float]]] = None  # fine-grained polygon if available


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    width: int = 0
    height: int = 0
    languages: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float:
        if not self.lines:
            return 0.0
        return sum(line.confidence for line in self.lines) / len(self.lines)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "languages": self.languages,
            "lines": [asdict(line) for line in self.lines],
        }


class OcrEngine:
    """Lazy Surya wrapper. Safe to share across asyncio tasks as long
    as the actual Surya invocation runs under a lock (Surya's models are
    not always thread-safe under concurrent calls)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._initialized = False
        self._det_predictor = None
        self._rec_predictor = None
        self._device: str = "cpu"

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            # Import inside the lock so we only pay the cost on first use.
            import torch  # noqa: F401 — required by surya

            from surya.detection import DetectionPredictor  # type: ignore
            from surya.recognition import RecognitionPredictor  # type: ignore

            # Respect SURYA_DEVICE / CLAIMSMAN_SURYA_DEVICE if set; default
            # to CPU so we don't fight other workloads for GPU memory.
            device = os.environ.get("CLAIMSMAN_SURYA_DEVICE") or os.environ.get(
                "SURYA_DEVICE"
            ) or "cpu"

            self._device = device
            self._det_predictor = DetectionPredictor()
            self._rec_predictor = RecognitionPredictor()
            self._initialized = True

    def recognize(
        self,
        image: Image.Image,
        *,
        languages: Optional[list[str]] = None,
    ) -> OcrResult:
        """Run Surya detection + recognition on a single page image."""
        self._initialize()
        assert self._det_predictor is not None
        assert self._rec_predictor is not None

        with self._lock:
            predictions = self._rec_predictor(
                [image.convert("RGB")],
                det_predictor=self._det_predictor,
            )

        if not predictions:
            return OcrResult(width=image.width, height=image.height, languages=languages or [])

        pred = predictions[0]
        result = OcrResult(
            width=image.width,
            height=image.height,
            languages=languages or [],
        )
        for line in getattr(pred, "text_lines", []) or []:
            text = getattr(line, "text", "") or ""
            bbox = getattr(line, "bbox", None) or []
            polygon = getattr(line, "polygon", None)
            confidence = getattr(line, "confidence", None)
            if confidence is None:
                confidence = 0.0
            result.lines.append(
                OcrLine(
                    text=str(text),
                    bbox=[float(x) for x in bbox] if bbox else [],
                    confidence=float(confidence),
                    polygon=[[float(x) for x in p] for p in polygon] if polygon else None,
                )
            )
        return result


_engine: Optional[OcrEngine] = None
_engine_lock = threading.Lock()


def get_ocr_engine() -> OcrEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = OcrEngine()
    return _engine
