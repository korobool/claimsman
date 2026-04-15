import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.web.db import get_session
from apps.web.logging_setup import logger
from apps.web.models import (
    AuditLog,
    Claim,
    ClaimStatus,
    Decision,
    DecisionOutcome,
    Document,
    Page,
    Upload,
)
from apps.web.pipeline import enqueue_claim
from apps.web.services.storage import storage

router = APIRouter(prefix="/claims", tags=["claims"])

ALLOWED_MIME_PREFIXES = (
    "image/",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
)

MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per file
MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB per bundle


def _is_allowed(mime: str) -> bool:
    return any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES)


@router.get("")
async def list_claims(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    result = await session.execute(
        select(Claim)
        .options(selectinload(Claim.uploads))
        .order_by(Claim.created_at.desc())
        .limit(200)
    )
    claims = result.scalars().all()
    return {"claims": [c.to_dict() for c in claims]}


@router.get("/{claim_id}")
async def get_claim(
    claim_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    claim = await _load_claim_full(session, claim_id)
    findings_by_severity = {"error": [], "warning": [], "info": []}
    for f in claim.findings:
        findings_by_severity.setdefault(f.severity.value, []).append(f.to_dict())
    decisions = sorted(
        claim.decisions,
        key=lambda d: (d.created_at or datetime.min),
        reverse=True,
    )
    proposed = next((d for d in decisions if d.is_proposed), None)
    confirmed = next((d for d in decisions if not d.is_proposed), None)
    stage_info = _compute_stage(claim, proposed)
    return {
        **claim.to_dict(),
        "uploads": [u.to_dict() for u in claim.uploads],
        "findings": [f.to_dict() for f in claim.findings],
        "findings_by_severity": findings_by_severity,
        "findings_summary": {
            "error": len(findings_by_severity.get("error", [])),
            "warning": len(findings_by_severity.get("warning", [])),
            "info": len(findings_by_severity.get("info", [])),
        },
        "proposed_decision": proposed.to_dict() if proposed else None,
        "confirmed_decision": confirmed.to_dict() if confirmed else None,
        "decisions": [d.to_dict() for d in decisions],
        "pipeline": stage_info,
        "documents": [
            {
                "id": str(d.id),
                "doc_type": d.doc_type,
                "display_name": d.display_name,
                "page_count": len(d.pages),
                "pages": [
                    {
                        "id": str(p.id),
                        "page_index": p.page_index,
                        "classification": p.classification,
                        "confidence": p.confidence,
                        "has_image": bool(p.image_path),
                        "text_layer_used": p.text_layer_used,
                        "ocr_text": p.ocr_text,
                        "ocr_preview": (p.ocr_text or "")[:600] if p.ocr_text else None,
                        "line_count": (
                            len((p.bbox_json or {}).get("lines", []))
                            if isinstance(p.bbox_json, dict)
                            else 0
                        ),
                        "width": (p.bbox_json or {}).get("width") if isinstance(p.bbox_json, dict) else None,
                        "height": (p.bbox_json or {}).get("height") if isinstance(p.bbox_json, dict) else None,
                        "ocr_lines": (p.bbox_json or {}).get("lines") if isinstance(p.bbox_json, dict) else None,
                    }
                    for p in sorted(d.pages, key=lambda x: x.page_index)
                ],
                "extracted_fields": [ef.to_dict() for ef in d.extracted_fields],
                "doc_stage": _compute_doc_stage(d),
            }
            for d in claim.documents
        ],
    }


class DecisionActionIn(BaseModel):
    outcome: str
    amount: float | None = None
    currency: str | None = None
    rationale_md: str | None = None
    reviewer: str | None = None


class ReprocessIn(BaseModel):
    stage: str = "ocr"  # ocr | classify | extract | analyze | decide | all
    document_id: uuid.UUID | None = None


class OcrLineEditIn(BaseModel):
    index: int
    text: str


class BBoxAddIn(BaseModel):
    text: str
    polygon: list[list[float]] | None = None
    bbox: list[float] | None = None
    confidence: float = 1.0


class BBoxRecognizeIn(BaseModel):
    bbox: list[float]
    polygon: list[list[float]] | None = None


@router.post("/{claim_id}/decision/confirm")
async def confirm_decision(
    claim_id: uuid.UUID,
    payload: DecisionActionIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    claim = await _load_claim_full(session, claim_id)
    try:
        outcome = DecisionOutcome(payload.outcome)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid outcome")

    proposed = next(
        (d for d in sorted(claim.decisions, key=lambda d: d.created_at, reverse=True) if d.is_proposed),
        None,
    )

    confirmed = Decision(
        claim_id=claim.id,
        kind="confirmed",
        outcome=outcome,
        amount=payload.amount if payload.amount is not None else (proposed.amount if proposed else None),
        currency=payload.currency if payload.currency is not None else (proposed.currency if proposed else None),
        rationale_md=payload.rationale_md
        if payload.rationale_md is not None
        else (proposed.rationale_md if proposed else None),
        is_proposed=False,
        llm_model=proposed.llm_model if proposed else None,
        confirmed_by=payload.reviewer or "reviewer",
        confirmed_at=datetime.now(timezone.utc),
    )
    session.add(confirmed)

    if outcome == DecisionOutcome.NEEDS_INFO:
        claim.status = ClaimStatus.ESCALATED
    else:
        claim.status = ClaimStatus.DECIDED

    session.add(
        AuditLog(
            actor=payload.reviewer or "reviewer",
            entity="claim",
            entity_id=claim.id,
            action=f"decision_confirm:{outcome.value}",
            before_json={"proposed": proposed.to_dict() if proposed else None},
            after_json=confirmed.to_dict(),
        )
    )

    await session.commit()
    logger.info(
        "decision.confirmed",
        claim_id=str(claim.id),
        outcome=outcome.value,
        reviewer=confirmed.confirmed_by,
    )
    await session.refresh(claim, ["decisions"])
    return {"claim_status": claim.status.value, "decision": confirmed.to_dict()}


@router.post("/{claim_id}/uploads")
async def add_uploads(
    claim_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    files: Annotated[list[UploadFile], File(description="Additional files to append")],
) -> dict:
    """Append one or more files to an existing claim and re-run the
    pipeline. Idempotent across stages: previously-processed pages are
    kept; new pages get ingest → OCR → classify → extract; analyze and
    decide regenerate across the full (old + new) document set."""
    if not files:
        raise HTTPException(status_code=400, detail="at least one file is required")
    claim = await _load_claim(session, claim_id)
    total = 0
    new_uploads: list[Upload] = []
    for f in files:
        content = await f.read()
        size = len(content)
        total += size
        if size > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename!r} too large")
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="bundle over total limit")
        mime = f.content_type or "application/octet-stream"
        if not _is_allowed(mime):
            raise HTTPException(status_code=415, detail=f"unsupported mime type {mime!r}")
        target, sha256 = await storage.save(
            claim_id=claim.id,
            filename=f.filename or "upload.bin",
            content=content,
        )
        u = Upload(
            claim_id=claim.id,
            filename=f.filename or "upload.bin",
            mime_type=mime,
            size_bytes=size,
            storage_path=str(target),
            sha256=sha256,
        )
        session.add(u)
        new_uploads.append(u)
    claim.status = ClaimStatus.PROCESSING
    session.add(
        AuditLog(
            actor="reviewer",
            entity="claim",
            entity_id=claim.id,
            action="add_uploads",
            after_json={"count": len(new_uploads), "filenames": [u.filename for u in new_uploads]},
        )
    )
    await session.commit()
    enqueue_claim(claim.id)
    logger.info(
        "claim.uploads_added",
        claim_id=str(claim.id),
        count=len(new_uploads),
        total_bytes=total,
    )
    return {
        "claim_id": str(claim.id),
        "status": claim.status.value,
        "added_count": len(new_uploads),
    }


@router.post("/{claim_id}/reprocess")
async def reprocess_claim(
    claim_id: uuid.UUID,
    payload: ReprocessIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Trigger a re-run of the pipeline for a claim.

    ``stage=all`` re-runs everything. Narrower stages run only the
    named stage forward; they clear the downstream rows (extracted
    fields, findings, proposed decisions) so the new run starts clean.
    """
    claim = await _load_claim_full(session, claim_id)
    # For v1 we always re-run the full pipeline; the stage hint will be
    # honored properly in a follow-up when the runner learns to resume
    # from a specific stage.
    claim.status = ClaimStatus.PROCESSING
    await session.commit()
    session.add(
        AuditLog(
            actor="reviewer",
            entity="claim",
            entity_id=claim.id,
            action=f"reprocess:{payload.stage}",
            after_json={"stage": payload.stage, "document_id": str(payload.document_id) if payload.document_id else None},
        )
    )
    await session.commit()
    enqueue_claim(claim.id)
    return {"claim_status": claim.status.value, "stage": payload.stage}


@router.patch("/{claim_id}/pages/{page_id}/ocr-line")
async def edit_ocr_line(
    claim_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: OcrLineEditIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    result = await session.execute(
        select(Page).join(Document).where(Page.id == page_id).where(Document.claim_id == claim_id)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    bbox = page.bbox_json if isinstance(page.bbox_json, dict) else {"lines": []}
    lines = bbox.get("lines") or []
    if payload.index < 0 or payload.index >= len(lines):
        raise HTTPException(status_code=400, detail="line index out of range")
    lines[payload.index]["text"] = payload.text
    bbox["lines"] = lines
    page.bbox_json = dict(bbox)  # force re-assignment for JSONB
    page.ocr_text = "\n".join(line.get("text", "") for line in lines)
    session.add(
        AuditLog(
            actor="reviewer",
            entity="page",
            entity_id=page.id,
            action="ocr_line_edit",
            after_json={"index": payload.index, "text": payload.text},
        )
    )
    await session.commit()
    return {"page_id": str(page.id), "line_index": payload.index, "text": payload.text}


@router.post("/{claim_id}/pages/{page_id}/bboxes/recognize")
async def recognize_region(
    claim_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: BBoxRecognizeIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Run Surya OCR on the user-drawn rectangle and persist a new
    manual-but-auto-recognized line. Used by the 'Add BBox' tool: the
    reviewer draws the rectangle, Surya recognizes the text, and the
    result is added to the page's OCR lines. The reviewer can still
    correct the text afterwards via the Edit-text tool."""
    import asyncio as _asyncio
    from pathlib import Path as _Path

    from PIL import Image as _Image

    from packages.ocr import get_ocr_engine

    result = await session.execute(
        select(Page).join(Document).where(Page.id == page_id).where(Document.claim_id == claim_id)
    )
    page = result.scalar_one_or_none()
    if page is None or not page.image_path:
        raise HTTPException(status_code=404, detail="page image not found")
    if not _Path(page.image_path).exists():
        raise HTTPException(status_code=410, detail="page image missing on disk")

    def _run_region_ocr() -> tuple[str, float]:
        engine = get_ocr_engine()
        with _Image.open(page.image_path) as img:
            ocr = engine.recognize_region(img, payload.bbox)
        if ocr.lines:
            lines_text = "\n".join(line.text for line in ocr.lines if line.text).strip()
            return lines_text, float(ocr.mean_confidence)
        return "", 0.0

    try:
        text, confidence = await _asyncio.to_thread(_run_region_ocr)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "page.bbox_recognize.error",
            claim_id=str(claim_id),
            page_id=str(page_id),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail=f"recognize failed: {exc}") from exc

    bbox_json = page.bbox_json if isinstance(page.bbox_json, dict) else {"lines": []}
    existing_lines = list(bbox_json.get("lines") or [])

    # Override behavior (ported from the reference prototype
    # app/static/js/app.js processNewBbox + bboxOverlaps): any existing
    # OCR line whose bbox overlaps the new user-drawn rectangle by more
    # than 30% of the existing bbox's area is removed. The reviewer is
    # saying "trust my rectangle, not Surya's detection" — so we wipe
    # Surya's overlapping lines and append the freshly-recognized one.
    kept_lines: list[dict] = []
    removed_count = 0
    for line in existing_lines:
        lb = line.get("bbox") or []
        if len(lb) == 4 and _bbox_overlaps(lb, payload.bbox, 0.30):
            removed_count += 1
            continue
        kept_lines.append(line)

    if payload.polygon is None:
        x0, y0, x1, y1 = payload.bbox
        polygon = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    else:
        polygon = payload.polygon
    new_line = {
        "text": text,
        "bbox": payload.bbox,
        "polygon": polygon,
        "confidence": confidence or 1.0,
        "manual": True,
        "auto_recognized": True,
    }
    kept_lines.append(new_line)
    kept_lines.sort(key=_line_sort_key)
    lines = kept_lines
    bbox_json["lines"] = lines
    page.bbox_json = dict(bbox_json)
    page.ocr_text = "\n".join(line.get("text", "") for line in lines)
    session.add(
        AuditLog(
            actor="reviewer",
            entity="page",
            entity_id=page.id,
            action="bbox_recognize",
            after_json={"bbox": payload.bbox, "text": text, "confidence": confidence},
        )
    )
    await session.commit()
    logger.info(
        "page.bbox_recognized",
        claim_id=str(claim_id),
        page_id=str(page_id),
        chars=len(text),
        confidence=round(confidence, 3),
        overridden=removed_count,
    )
    return {
        "page_id": str(page.id),
        "line_count": len(lines),
        "overridden": removed_count,
        "text": text,
        "confidence": confidence,
    }


def _bbox_overlaps(a: list[float], b: list[float], threshold: float) -> bool:
    """Return True if the intersection of a and b is more than
    ``threshold`` of a's area.

    Matches the reference project's bboxOverlaps(app.js) logic: compare
    the intersection area to the existing line's area, not the new
    one's — so a small existing line fully inside a big new box still
    counts as 'overlap 100%' and gets removed."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    if ax1 >= bx2 or ax2 <= bx1 or ay1 >= by2 or ay2 <= by1:
        return False
    inter_w = min(ax2, bx2) - max(ax1, bx1)
    inter_h = min(ay2, by2) - max(ay1, by1)
    inter = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    if area_a <= 0:
        return False
    return inter > area_a * threshold


def _line_sort_key(line: dict) -> tuple[float, float]:
    b = line.get("bbox") or []
    if len(b) == 4:
        return (float(b[1]), float(b[0]))
    return (0.0, 0.0)


@router.post("/{claim_id}/pages/{page_id}/bboxes")
async def add_bbox(
    claim_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: BBoxAddIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    result = await session.execute(
        select(Page).join(Document).where(Page.id == page_id).where(Document.claim_id == claim_id)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    bbox = page.bbox_json if isinstance(page.bbox_json, dict) else {"lines": []}
    lines = list(bbox.get("lines") or [])
    lines.append(
        {
            "text": payload.text,
            "bbox": payload.bbox or [],
            "confidence": float(payload.confidence),
            "polygon": payload.polygon,
            "manual": True,
        }
    )
    bbox["lines"] = lines
    page.bbox_json = dict(bbox)
    page.ocr_text = "\n".join(line.get("text", "") for line in lines)
    session.add(
        AuditLog(
            actor="reviewer",
            entity="page",
            entity_id=page.id,
            action="bbox_add",
            after_json={"text": payload.text, "polygon": payload.polygon},
        )
    )
    await session.commit()
    return {"page_id": str(page.id), "line_index": len(lines) - 1, "text": payload.text}


@router.post("/{claim_id}/decision/reopen")
async def reopen_decision(
    claim_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    claim = await _load_claim_full(session, claim_id)
    claim.status = ClaimStatus.UNDER_REVIEW
    session.add(
        AuditLog(
            actor="reviewer",
            entity="claim",
            entity_id=claim.id,
            action="decision_reopen",
            after_json={"status": claim.status.value},
        )
    )
    await session.commit()
    return {"claim_status": claim.status.value}


@router.get("/{claim_id}/pages/{page_id}/image")
async def get_page_image(
    claim_id: uuid.UUID,
    page_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    result = await session.execute(
        select(Page).join(Document).where(Page.id == page_id).where(Document.claim_id == claim_id)
    )
    page = result.scalar_one_or_none()
    if page is None or not page.image_path:
        raise HTTPException(status_code=404, detail="page image not found")
    path = Path(page.image_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="page image missing on disk")
    return FileResponse(path, media_type="image/png")


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_claim(
    session: Annotated[AsyncSession, Depends(get_session)],
    files: Annotated[list[UploadFile], File(description="Claim bundle files")],
    claimant_name: Annotated[str | None, Form()] = None,
    policy_number: Annotated[str | None, Form()] = None,
    domain: Annotated[str, Form()] = "health_insurance",
    title: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="at least one file is required")

    claim = Claim(
        code=Claim.new_code(),
        title=title,
        claimant_name=claimant_name,
        policy_number=policy_number,
        domain=domain,
        notes=notes,
        status=ClaimStatus.UPLOADED,
    )
    session.add(claim)
    await session.flush()

    total = 0
    for f in files:
        content = await f.read()
        size = len(content)
        total += size
        if size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"file {f.filename!r} exceeds per-file limit of {MAX_FILE_BYTES} bytes",
            )
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"bundle exceeds total limit of {MAX_TOTAL_BYTES} bytes",
            )
        mime = f.content_type or "application/octet-stream"
        if not _is_allowed(mime):
            raise HTTPException(
                status_code=415,
                detail=f"unsupported mime type {mime!r} for {f.filename!r}",
            )
        target, sha256 = await storage.save(
            claim_id=claim.id,
            filename=f.filename or "upload.bin",
            content=content,
        )
        session.add(
            Upload(
                claim_id=claim.id,
                filename=f.filename or "upload.bin",
                mime_type=mime,
                size_bytes=size,
                storage_path=str(target),
                sha256=sha256,
            )
        )

    await session.commit()
    await session.refresh(claim, ["uploads"])
    logger.info(
        "claim.created",
        claim_id=str(claim.id),
        code=claim.code,
        upload_count=len(claim.uploads),
        total_bytes=total,
    )
    # Kick off the in-process pipeline (ingest → normalize → ocr → …).
    # This is fire-and-forget; the frontend polls or listens for updates.
    enqueue_claim(claim.id)
    return {
        **claim.to_dict(),
        "uploads": [u.to_dict() for u in claim.uploads],
    }


STAGE_ORDER = [
    "ingest",
    "ocr",
    "classify",
    "extract",
    "analyze",
    "decide",
]
STAGE_WEIGHTS = {
    "ingest": 0.05,
    "ocr": 0.55,
    "classify": 0.10,
    "extract": 0.20,
    "analyze": 0.05,
    "decide": 0.05,
}


def _compute_stage(claim: Claim, proposed: Decision | None) -> dict:
    """Derive a pipeline-stage snapshot from the current claim state.

    Returned shape:
        {
          "stage": "ocr" | "classify" | ..., (or "ready" | "error" | "decided")
          "label": "Running OCR",
          "active": bool,        # true while pipeline is still working
          "progress": 0.0..1.0,  # overall, derived from stage weights + within-stage progress
          "totals": {pages, pages_ocr, pages_classified, docs, docs_extracted}
        }
    """
    all_pages = [p for d in claim.documents for p in d.pages]
    pages_total = len(all_pages)
    pages_with_image = sum(1 for p in all_pages if p.image_path)
    pages_ocr = sum(1 for p in all_pages if p.ocr_text or p.text_layer_used)
    pages_classified = sum(1 for p in all_pages if p.classification)
    docs_total = len(claim.documents)
    docs_extracted = sum(1 for d in claim.documents if d.extracted_fields)

    totals = {
        "pages": pages_total,
        "pages_with_image": pages_with_image,
        "pages_ocr": pages_ocr,
        "pages_classified": pages_classified,
        "docs": docs_total,
        "docs_extracted": docs_extracted,
    }

    status = claim.status.value if hasattr(claim.status, "value") else str(claim.status)

    if status == "error":
        return {"stage": "error", "label": "Error", "active": False, "progress": 0.0, "totals": totals}
    if status in ("decided", "escalated"):
        return {"stage": status, "label": status.replace("_", " ").title(), "active": False, "progress": 1.0, "totals": totals}
    if status == "ready_for_review":
        return {"stage": "ready", "label": "Ready for review", "active": False, "progress": 1.0, "totals": totals}

    # Still processing → derive the active stage from the data
    if docs_total == 0:
        stage = "ingest"
        within = 0.0
    elif pages_with_image > 0 and pages_ocr < pages_with_image:
        stage = "ocr"
        within = pages_ocr / pages_with_image if pages_with_image else 0.0
    elif pages_total > 0 and pages_classified < pages_total:
        stage = "classify"
        within = pages_classified / pages_total if pages_total else 0.0
    elif docs_total > 0 and docs_extracted < docs_total:
        stage = "extract"
        within = docs_extracted / docs_total if docs_total else 0.0
    elif not claim.findings:
        stage = "analyze"
        within = 0.5
    elif proposed is None:
        stage = "decide"
        within = 0.5
    else:
        stage = "decide"
        within = 1.0

    # Overall progress: sum weights of completed stages + within-stage weight.
    idx = STAGE_ORDER.index(stage)
    progress = sum(STAGE_WEIGHTS[s] for s in STAGE_ORDER[:idx]) + STAGE_WEIGHTS[stage] * within

    labels = {
        "ingest": "Ingesting documents",
        "ocr": f"OCR ({pages_ocr}/{pages_with_image} pages)" if pages_with_image else "Running OCR",
        "classify": f"Classifying ({pages_classified}/{pages_total} pages)" if pages_total else "Classifying",
        "extract": f"Extracting fields ({docs_extracted}/{docs_total} docs)" if docs_total else "Extracting fields",
        "analyze": "Analyzing findings",
        "decide": "Proposing decision",
    }
    return {
        "stage": stage,
        "label": labels[stage],
        "active": True,
        "progress": round(progress, 3),
        "totals": totals,
    }


def _compute_doc_stage(doc: Document) -> str:
    """Per-document stage: used to show a spinner next to each document
    in the Claim Detail left rail while work is in flight on that doc."""
    pages = list(doc.pages)
    if not pages:
        return "pending"
    if any(p.image_path and not (p.ocr_text or p.text_layer_used) for p in pages):
        return "ocr"
    if any(not p.classification for p in pages):
        return "classify"
    if not doc.extracted_fields:
        return "extract"
    return "ready"


async def _load_claim(session: AsyncSession, claim_id: uuid.UUID) -> Claim:
    result = await session.execute(
        select(Claim).options(selectinload(Claim.uploads)).where(Claim.id == claim_id)
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim


async def _load_claim_full(session: AsyncSession, claim_id: uuid.UUID) -> Claim:
    result = await session.execute(
        select(Claim)
        .options(
            selectinload(Claim.uploads),
            selectinload(Claim.documents).selectinload(Document.pages),
            selectinload(Claim.documents).selectinload(Document.extracted_fields),
            selectinload(Claim.findings),
            selectinload(Claim.decisions),
        )
        .where(Claim.id == claim_id)
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim
