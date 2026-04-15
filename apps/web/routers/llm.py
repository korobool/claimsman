"""Admin endpoints for the local Ollama LLM instance.

Exposes:
- GET  /api/v1/llm/models — list installed models with size + vision tag
- POST /api/v1/llm/pull/{tag} — pull a new model from Ollama's registry
- GET  /api/v1/llm/pull/{job_id} — poll a pull job's streaming status
- GET  /api/v1/llm/status — quick reachability + default-model report
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.web.config import settings
from apps.web.logging_setup import logger

router = APIRouter(prefix="/llm", tags=["llm"])

VISION_HINTS = ("gemma4", "llava", "minicpm-v", "moondream", "qwen-vl", "llama-vision", "pixtral")


@dataclass
class PullJob:
    job_id: str
    tag: str
    status: str = "queued"  # queued | running | done | error
    message: str = ""
    total: int = 0
    completed: int = 0
    events: list[dict] = field(default_factory=list)


_pull_jobs: dict[str, PullJob] = {}


@router.get("/status")
async def llm_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        models = data.get("models") or []
        return {
            "reachable": True,
            "base_url": settings.ollama_base_url,
            "default_model": settings.ollama_default_model,
            "model_count": len(models),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "reachable": False,
            "base_url": settings.ollama_base_url,
            "default_model": settings.ollama_default_model,
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.get("/models")
async def list_models() -> dict:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ollama unreachable: {exc}") from exc

    models = []
    for m in data.get("models") or []:
        name = m.get("name") or ""
        lower = name.lower()
        vision = any(h in lower for h in VISION_HINTS)
        models.append(
            {
                "name": name,
                "size": m.get("size"),
                "modified_at": m.get("modified_at"),
                "digest": m.get("digest"),
                "family": (m.get("details") or {}).get("family"),
                "parameter_size": (m.get("details") or {}).get("parameter_size"),
                "vision": vision,
                "is_default": name == settings.ollama_default_model,
            }
        )
    models.sort(key=lambda m: (not m["is_default"], not m["vision"], m["name"]))
    return {"models": models, "default_model": settings.ollama_default_model}


class PullIn(BaseModel):
    tag: str


@router.post("/pull")
async def pull_model(payload: PullIn) -> dict:
    tag = payload.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="tag is required")
    job_id = uuid.uuid4().hex
    job = PullJob(job_id=job_id, tag=tag, status="queued")
    _pull_jobs[job_id] = job
    asyncio.create_task(_run_pull(job))
    logger.info("llm.pull.enqueued", job_id=job_id, tag=tag)
    return {"job_id": job_id, "status": job.status, "tag": tag}


@router.get("/pull/{job_id}")
async def pull_status(job_id: str) -> dict:
    job = _pull_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job_id": job.job_id,
        "tag": job.tag,
        "status": job.status,
        "message": job.message,
        "total": job.total,
        "completed": job.completed,
        "events": job.events[-10:],
    }


async def _run_pull(job: PullJob) -> None:
    job.status = "running"
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{settings.ollama_base_url}/api/pull",
                json={"name": job.tag, "stream": True},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        import json as _json

                        event: dict[str, Any] = _json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    status_line = event.get("status") or ""
                    if isinstance(event.get("total"), int):
                        job.total = int(event["total"])
                    if isinstance(event.get("completed"), int):
                        job.completed = int(event["completed"])
                    job.message = status_line
                    if len(job.events) < 200:
                        job.events.append(
                            {
                                "status": status_line,
                                "completed": job.completed,
                                "total": job.total,
                            }
                        )
                    if status_line == "success":
                        job.status = "done"
                        break
        if job.status != "done":
            job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.message = f"{type(exc).__name__}: {exc}"
        logger.error("llm.pull.error", job_id=job.job_id, error=job.message)
