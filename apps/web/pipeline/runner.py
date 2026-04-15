"""In-process pipeline runner.

One Python process — no Celery, no RQ, no Redis. Stages are async
coroutines scheduled on the FastAPI event loop; CPU/IO-heavy work runs
in ``asyncio.to_thread``. Each stage updates the claim status in
Postgres so a process restart can pick up where it left off.

M2.4a ships only the ``ingest`` stage. Later milestones add
normalize / ocr / classify / extract / assemble / analyze / decide.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.web.config import settings
from apps.web.db import SessionLocal
from apps.web.logging_setup import logger
from apps.web.models import Claim, ClaimStatus, Document, ExtractedField, Page, Upload
from packages.extract import get_extractor
from packages.ingest import IngestedDocument, SourceKind, ingest_file
from packages.ocr import OcrResult, get_ocr_engine
from packages.vision import get_classifier


def enqueue_claim(claim_id: uuid.UUID) -> asyncio.Task:
    """Fire-and-forget entry point used by the API layer.

    Returns the created task so callers can keep a strong reference
    (otherwise asyncio may garbage-collect it mid-run).
    """
    task = asyncio.create_task(
        run_claim_pipeline(claim_id),
        name=f"claim-pipeline:{claim_id}",
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def run_claim_pipeline(claim_id: uuid.UUID) -> None:
    logger.info("pipeline.start", claim_id=str(claim_id))
    try:
        async with SessionLocal() as session:
            claim = await _load_claim_with_uploads(session, claim_id)
            if claim is None:
                logger.warning("pipeline.claim_missing", claim_id=str(claim_id))
                return

            claim.status = ClaimStatus.PROCESSING
            await session.commit()

            await _stage_ingest(session, claim)
            await session.commit()
            await _stage_ocr(session, claim)
            await session.commit()
            await _stage_classify(session, claim)
            await session.commit()
            await _stage_extract(session, claim)
            await session.commit()
            logger.info(
                "pipeline.done",
                claim_id=str(claim_id),
                stages="ingest+ocr+classify+extract",
                status=claim.status.value,
            )
    except Exception as exc:  # noqa: BLE001 — last-resort logger
        logger.error(
            "pipeline.error",
            claim_id=str(claim_id),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        try:
            async with SessionLocal() as session:
                claim = await session.get(Claim, claim_id)
                if claim is not None:
                    claim.status = ClaimStatus.ERROR
                    await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("pipeline.error_flag_failed", claim_id=str(claim_id))


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


async def _stage_ingest(session: AsyncSession, claim: Claim) -> None:
    """Rasterize every upload into Document + Page rows.

    Each upload becomes a single Document; multi-page PDFs produce many
    Page rows under one Document. This is a naive v1 grouping — smarter
    clustering lands in the ``group`` stage in a later milestone.
    """
    pages_root = Path(settings.storage_root).parent / "pages" / str(claim.id)

    for upload in claim.uploads:
        # Skip if we already created a document for this upload in a
        # previous run (idempotency).
        already = await session.execute(
            select(Document)
            .where(Document.claim_id == claim.id)
            .where(Document.display_name == upload.filename)
        )
        if already.scalar_one_or_none() is not None:
            logger.info(
                "pipeline.ingest.skip_existing",
                claim_id=str(claim.id),
                upload=upload.filename,
            )
            continue

        ingested = await asyncio.to_thread(
            ingest_file,
            Path(upload.storage_path),
            pages_root / str(upload.id),
            mime_hint=upload.mime_type,
        )

        doc = Document(
            claim_id=claim.id,
            doc_type=_doc_type_for_source(ingested),
            display_name=upload.filename,
        )
        session.add(doc)
        await session.flush()

        for p in ingested.pages:
            session.add(
                Page(
                    document_id=doc.id,
                    upload_id=upload.id,
                    page_index=p.page_index,
                    image_path=str(p.image_path) if p.image_path else None,
                    ocr_text=p.text_layer,
                    classification=None,
                    confidence=None,
                    bbox_json=None,
                    text_layer_used=p.text_layer_used,
                )
            )

        logger.info(
            "pipeline.ingest.document",
            claim_id=str(claim.id),
            document_id=str(doc.id),
            source_kind=ingested.kind.value,
            pages=len(ingested.pages),
            note=ingested.note,
        )


def _doc_type_for_source(ing: IngestedDocument) -> str:
    if ing.kind in (SourceKind.PDF_SCANNED, SourceKind.PDF_TEXT_LAYER):
        return "unknown"  # classification stage will refine
    if ing.kind == SourceKind.IMAGE:
        return "unknown"
    if ing.kind == SourceKind.DOCX:
        return "correspondence"
    return "unknown"


async def _stage_ocr(session: AsyncSession, claim: Claim) -> None:
    """Run Surya OCR on every page that needs it."""
    # Freshly load the claim with pages (the previous stage_ingest
    # added new rows; we need to see them here).
    result = await session.execute(
        select(Page)
        .join(Document)
        .where(Document.claim_id == claim.id)
        .order_by(Document.id, Page.page_index)
    )
    pages = result.scalars().all()

    for page in pages:
        if page.ocr_text and not page.bbox_json:
            # Text-layer PDF: we already have text; skip OCR.
            continue
        if page.bbox_json:
            # Already OCR'd in an earlier run.
            continue
        if not page.image_path:
            continue
        try:
            ocr = await asyncio.to_thread(_run_ocr_on_path, Path(page.image_path))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "pipeline.ocr.error",
                claim_id=str(claim.id),
                page_id=str(page.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            continue

        page.ocr_text = ocr.text
        page.bbox_json = ocr.to_dict()
        logger.info(
            "pipeline.ocr.page",
            claim_id=str(claim.id),
            page_id=str(page.id),
            lines=len(ocr.lines),
            mean_confidence=round(ocr.mean_confidence, 3),
        )


def _run_ocr_on_path(image_path: Path) -> OcrResult:
    engine = get_ocr_engine()
    with Image.open(image_path) as img:
        return engine.recognize(img)


async def _stage_classify(session: AsyncSession, claim: Claim) -> None:
    """Run SigLIP 2 zero-shot classification on every page image, then
    assign the Document.doc_type by majority vote."""
    result = await session.execute(
        select(Page)
        .join(Document)
        .where(Document.claim_id == claim.id)
        .options(selectinload(Page.document))
        .order_by(Document.id, Page.page_index)
    )
    pages = result.scalars().all()

    per_doc_labels: dict[uuid.UUID, list[str]] = {}

    for page in pages:
        if page.classification:
            per_doc_labels.setdefault(page.document_id, []).append(page.classification)
            continue
        if not page.image_path:
            continue
        try:
            classification = await asyncio.to_thread(_run_classify_on_path, Path(page.image_path))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "pipeline.classify.error",
                claim_id=str(claim.id),
                page_id=str(page.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            continue

        label = _normalize_label(classification.label)
        page.classification = label
        page.confidence = classification.score
        per_doc_labels.setdefault(page.document_id, []).append(label)
        logger.info(
            "pipeline.classify.page",
            claim_id=str(claim.id),
            page_id=str(page.id),
            label=label,
            score=round(classification.score, 3),
        )

    # Assign a doc_type to each Document based on the majority label.
    for doc_id, labels in per_doc_labels.items():
        if not labels:
            continue
        winner, _ = Counter(labels).most_common(1)[0]
        doc = await session.get(Document, doc_id)
        if doc is not None and doc.doc_type in ("unknown", ""):
            doc.doc_type = winner


def _run_classify_on_path(image_path: Path):
    classifier = get_classifier()
    with Image.open(image_path) as img:
        return classifier.classify(img)


def _normalize_label(label: str) -> str:
    """Turn "medical report" → "medical_report" so labels match the
    snake_case doc_type convention used in config/schemas/*.yaml."""
    return label.strip().lower().replace(" ", "_")


async def _stage_extract(session: AsyncSession, claim: Claim) -> None:
    """Run the LLM (Ollama Gemma 4) against each Document with the
    schema that matches the Document.doc_type, persisting each returned
    field as an ExtractedField row."""
    result = await session.execute(
        select(Document)
        .where(Document.claim_id == claim.id)
        .options(
            selectinload(Document.pages),
            selectinload(Document.extracted_fields),
        )
    )
    documents = result.scalars().all()
    extractor = get_extractor()

    for doc in documents:
        if doc.extracted_fields:
            continue  # already extracted in a prior run
        ocr_text = "\n".join(p.ocr_text or "" for p in sorted(doc.pages, key=lambda x: x.page_index) if p.ocr_text)
        image_paths = [Path(p.image_path) for p in sorted(doc.pages, key=lambda x: x.page_index) if p.image_path]
        try:
            extraction = await extractor.extract(
                doc_type=doc.doc_type or "unknown",
                domain_code=claim.domain,
                ocr_text=ocr_text,
                image_paths=image_paths,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "pipeline.extract.error",
                claim_id=str(claim.id),
                document_id=str(doc.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            continue

        if extraction.error:
            logger.error(
                "pipeline.extract.error",
                claim_id=str(claim.id),
                document_id=str(doc.id),
                error=extraction.error,
            )
            continue

        for key, value in extraction.fields.items():
            session.add(
                ExtractedField(
                    document_id=doc.id,
                    schema_key=key,
                    value_json=value,
                    confidence=None,
                    source_bbox_json=None,
                    llm_model=extraction.model,
                    llm_rationale=None,
                )
            )
        logger.info(
            "pipeline.extract.document",
            claim_id=str(claim.id),
            document_id=str(doc.id),
            doc_type=doc.doc_type,
            fields_count=len(extraction.fields),
            model=extraction.model,
            vision_used=extraction.vision_used,
        )


async def _load_claim_with_uploads(
    session: AsyncSession, claim_id: uuid.UUID
) -> Claim | None:
    result = await session.execute(
        select(Claim)
        .options(
            selectinload(Claim.uploads),
            selectinload(Claim.documents).selectinload(Document.pages),
        )
        .where(Claim.id == claim_id)
    )
    return result.scalar_one_or_none()
