import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.web.db import get_session
from apps.web.logging_setup import logger
from apps.web.models import Claim, ClaimStatus, Document, Page, Upload
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
    return {
        **claim.to_dict(),
        "uploads": [u.to_dict() for u in claim.uploads],
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
                        "ocr_preview": (p.ocr_text or "")[:160] if p.ocr_text else None,
                    }
                    for p in sorted(d.pages, key=lambda x: x.page_index)
                ],
            }
            for d in claim.documents
        ],
    }


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
        )
        .where(Claim.id == claim_id)
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim
