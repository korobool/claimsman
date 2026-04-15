"""Settings → Health panel data.

Returns everything the admin screen needs to check that the single
Python process, Postgres, Ollama, Surya, and SigLIP 2 are all alive
and what hardware they are running on.
"""
from __future__ import annotations

import os
import platform
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.web.config import settings
from apps.web.db import get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/panels")
async def health_panels(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    return {
        "process": _process_panel(),
        "device": _device_panel(),
        "database": await _database_panel(session),
        "ollama": await _ollama_panel(),
        "surya": _surya_panel(),
        "siglip": _siglip_panel(),
    }


def _process_panel() -> dict:
    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "env": settings.env,
        "host": settings.host,
        "port": settings.port,
        "pid": os.getpid(),
    }


def _device_panel() -> dict:
    info: dict = {
        "cpu_count": os.cpu_count(),
        "torch": None,
        "cuda": False,
        "mps": False,
        "device_name": None,
    }
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["device_name"] = torch.cuda.get_device_name(0)
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            info["mps"] = True
            info["device_name"] = "Apple MPS"
        else:
            info["device_name"] = "CPU"
    except Exception:  # noqa: BLE001
        info["torch"] = "not installed"
    return info


async def _database_panel(session: AsyncSession) -> dict:
    try:
        result = await session.execute(text("SELECT version()"))
        version = result.scalar_one()
        return {
            "reachable": True,
            "url": f"postgresql://{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
            "version": version,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "reachable": False,
            "url": f"postgresql://{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _ollama_panel() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        return {
            "reachable": True,
            "url": settings.ollama_base_url,
            "default_model": settings.ollama_default_model,
            "model_count": len(data.get("models") or []),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "reachable": False,
            "url": settings.ollama_base_url,
            "default_model": settings.ollama_default_model,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _surya_panel() -> dict:
    try:
        from packages.ocr.surya import get_ocr_engine

        engine = get_ocr_engine()
        return {
            "available": True,
            "loaded": engine._initialized,  # noqa: SLF001
            "device": engine._device,  # noqa: SLF001
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def _siglip_panel() -> dict:
    try:
        from packages.vision.siglip import DEFAULT_MODEL, get_classifier

        classifier = get_classifier()
        return {
            "available": True,
            "loaded": classifier._initialized,  # noqa: SLF001
            "device": classifier._device,  # noqa: SLF001
            "model": DEFAULT_MODEL,
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
