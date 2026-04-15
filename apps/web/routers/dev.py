"""A live development-state dashboard endpoint.

Returns everything needed to build an in-browser view that shows what
Claimsman currently knows about itself: milestone, recent commits,
schema/domain counts, pipeline activity, server health. It is meant
for the human reviewer to watch progress during autonomous
development — it is NOT an admin/reviewer feature in the product
sense.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.web import __version__
from apps.web.config import settings
from apps.web.db import get_session
from apps.web.models import Claim, Document, ExtractedField, Page, Upload
from packages.schemas import get_domains, get_schemas

router = APIRouter(prefix="/dev", tags=["dev"])


CURRENT_MILESTONE = {
    "id": "M5",
    "label": "Decisioning engine + reviewer workflow",
    "phase": "M5",
    "description": (
        "Deterministic rule gates + Gemma 4 reasoning propose a decision "
        "(approve / partial / deny / needs_info), amount, and markdown "
        "rationale. Reviewer approve/edit/reject actions persist as "
        "audited Decision rows and transition the claim state."
    ),
    "completed_milestones": [
        "M1 — skeleton",
        "M2.4a — in-process pipeline + ingest",
        "M2.4b — Surya OCR + SigLIP classification",
        "M3 — LLM extraction + schemas/domains + bbox overlay + Domains admin",
        "M4 — findings engine + health/motor rule modules",
    ],
    "next_milestones": [
        "M6 — admin UIs (Schemas, LLM, Health)",
        "M7 — accessibility + polish + runbook",
    ],
}

REPO_ROOT = Path(__file__).resolve().parents[3]


@router.get("/state")
async def dev_state(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    schemas = get_schemas()
    domains = get_domains()

    claim_count = (await session.execute(select(func.count(Claim.id)))).scalar() or 0
    upload_count = (await session.execute(select(func.count(Upload.id)))).scalar() or 0
    doc_count = (await session.execute(select(func.count(Document.id)))).scalar() or 0
    page_count = (await session.execute(select(func.count(Page.id)))).scalar() or 0
    ef_count = (await session.execute(select(func.count(ExtractedField.id)))).scalar() or 0

    recent_claims = await session.execute(
        select(Claim).order_by(Claim.created_at.desc()).limit(8)
    )
    recent = [
        {
            "id": str(c.id),
            "code": c.code,
            "title": c.title,
            "claimant_name": c.claimant_name,
            "domain": c.domain,
            "status": c.status.value,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in recent_claims.scalars().all()
    ]

    ollama_status = await _ollama_status()
    git = _git_state()

    return {
        "app": {
            "name": "claimsman",
            "version": __version__,
            "env": settings.env,
            "port": settings.port,
            "base_url": f"http://{settings.host}:{settings.port}",
        },
        "milestone": CURRENT_MILESTONE,
        "git": git,
        "config": {
            "schemas": {
                "count": len(schemas.all()),
                "doc_types": schemas.doc_types(),
            },
            "domains": {
                "count": len(domains.all()),
                "codes": domains.codes(),
            },
        },
        "db": {
            "claims": claim_count,
            "uploads": upload_count,
            "documents": doc_count,
            "pages": page_count,
            "extracted_fields": ef_count,
        },
        "recent_claims": recent,
        "ollama": ollama_status,
    }


def _git_state() -> dict:
    try:
        head = _git(["rev-parse", "--short", "HEAD"])
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        log = _git(["log", "-n", "10", "--pretty=format:%h|%an|%ar|%s"])
        commits = []
        for raw in log.splitlines():
            parts = raw.split("|", 3)
            if len(parts) == 4:
                commits.append(
                    {
                        "sha": parts[0],
                        "author": parts[1],
                        "when": parts[2],
                        "subject": parts[3],
                    }
                )
        return {"head": head, "branch": branch, "commits": commits}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT)] + args,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


async def _ollama_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = [
                {"name": m.get("name"), "size": m.get("size")}
                for m in (data.get("models") or [])[:20]
            ]
            return {
                "reachable": True,
                "url": settings.ollama_base_url,
                "default_model": settings.ollama_default_model,
                "model_count": len(data.get("models") or []),
                "models_sample": models,
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "reachable": False,
            "url": settings.ollama_base_url,
            "default_model": settings.ollama_default_model,
            "error": f"{type(exc).__name__}: {exc}",
        }
