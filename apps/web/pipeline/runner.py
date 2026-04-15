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
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.web.config import settings
from apps.web.db import SessionLocal
from apps.web.logging_setup import logger
from apps.web.models import Claim, ClaimStatus, Document, Page, Upload
from packages.ingest import IngestedDocument, SourceKind, ingest_file


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
            # Later: normalize, ocr, classify, group, extract, assemble,
            # analyze, decide. For now stop here and leave the claim in
            # PROCESSING so the reviewer can see pages without a decision.
            await session.commit()
            logger.info(
                "pipeline.done",
                claim_id=str(claim_id),
                stage="ingest",
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
