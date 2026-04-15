"""Zero-shot document classification via SigLIP 2 (or SigLIP v1 fallback).

Takes a PIL page image and a list of candidate doc-type labels (from
``config/schemas/*``) and returns a ranked list of (label, score). The
model loads lazily on first call and stays in memory.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional

from PIL import Image

DEFAULT_MODEL = os.environ.get(
    "CLAIMSMAN_SIGLIP_MODEL",
    "google/siglip-base-patch16-224",
)

DEFAULT_LABELS = [
    "prescription",
    "receipt",
    "invoice",
    "medical report",
    "discharge summary",
    "insurance card",
    "repair estimate",
    "repair invoice",
    "police report",
    "driver license",
    "vehicle registration",
    "photo of vehicle damage",
    "correspondence",
    "unknown document",
]

# Each candidate label becomes "A scanned photo of a {label}." — that
# is the prompt Siglip/CLIP-family models expect for zero-shot image
# classification and it dramatically improves accuracy.
LABEL_TEMPLATE = "A scanned photo of a {label}."


@dataclass
class ClassificationResult:
    label: str
    score: float
    all_scores: list[tuple[str, float]]


class SigLipClassifier:
    def __init__(self, model_id: str = DEFAULT_MODEL) -> None:
        self.model_id = model_id
        self._lock = threading.Lock()
        self._initialized = False
        self._model = None
        self._processor = None
        self._device = "cpu"

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            import torch

            try:
                from transformers import AutoModel, AutoProcessor
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "transformers is required for SigLipClassifier"
                ) from exc

            device = os.environ.get("CLAIMSMAN_SIGLIP_DEVICE") or "cpu"
            self._device = device
            self._processor = AutoProcessor.from_pretrained(self.model_id)
            self._model = AutoModel.from_pretrained(self.model_id)
            if device != "cpu":
                self._model = self._model.to(device)  # type: ignore[attr-defined]
            self._model.eval()  # type: ignore[attr-defined]
            self._torch = torch
            self._initialized = True

    def classify(
        self,
        image: Image.Image,
        candidate_labels: Optional[list[str]] = None,
    ) -> ClassificationResult:
        self._initialize()
        assert self._model is not None
        assert self._processor is not None

        labels = list(candidate_labels or DEFAULT_LABELS)
        prompts = [LABEL_TEMPLATE.format(label=label) for label in labels]

        torch = self._torch
        with self._lock, torch.no_grad():
            inputs = self._processor(
                text=prompts,
                images=image.convert("RGB"),
                padding="max_length",
                return_tensors="pt",
            )
            if self._device != "cpu":
                inputs = {k: v.to(self._device) for k, v in inputs.items()}
            outputs = self._model(**inputs)
            logits_per_image = outputs.logits_per_image  # (1, num_labels)
            probs = torch.sigmoid(logits_per_image).squeeze(0).tolist()

        paired = sorted(
            ((label, float(score)) for label, score in zip(labels, probs)),
            key=lambda lp: lp[1],
            reverse=True,
        )
        best = paired[0]
        return ClassificationResult(label=best[0], score=best[1], all_scores=paired)


_classifier: Optional[SigLipClassifier] = None
_classifier_lock = threading.Lock()


def get_classifier() -> SigLipClassifier:
    global _classifier
    if _classifier is None:
        with _classifier_lock:
            if _classifier is None:
                _classifier = SigLipClassifier()
    return _classifier
