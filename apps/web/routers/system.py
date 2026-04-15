from fastapi import APIRouter

from apps.web import __version__
from apps.web.config import settings

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "version": __version__, "env": settings.env}


@router.get("/info")
async def info() -> dict:
    return {
        "name": "claimsman",
        "version": __version__,
        "env": settings.env,
        "ollama": {
            "base_url": settings.ollama_base_url,
            "default_model": settings.ollama_default_model,
        },
    }
