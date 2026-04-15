"""Admin CRUD for domain packs (spec §4.7 F-7.2, §11.2 screen #12).

Stored as YAML files under ``config/domains/*.yaml``. Each mutation
rewrites the file and reloads the in-memory registry. This is a
single-tenant admin surface — authentication is intentionally minimal
in v1 and will be added alongside the login milestone.
"""
from __future__ import annotations

import re
from typing import Annotated

import yaml
from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, Field

from apps.web.logging_setup import logger
from packages.extract import generate_domain_from_description
from packages.schemas import DomainPack, get_domains

router = APIRouter(prefix="/domains", tags=["domains"])

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class DomainIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,63}$")
    display_name: str
    description: str = ""
    vocabulary: dict = Field(default_factory=dict)
    required_documents: list[dict] = Field(default_factory=list)
    rule_module: str = ""
    decision_prompt_snippet: str = ""
    thresholds: dict = Field(default_factory=dict)


class DomainYamlIn(BaseModel):
    yaml: str


class DomainGenerateIn(BaseModel):
    description: str
    model: str | None = None


@router.get("")
async def list_domains() -> dict:
    registry = get_domains()
    return {"domains": [_pack_to_api(p) for p in registry.all()]}


@router.get("/{code}")
async def get_domain(code: str) -> dict:
    registry = get_domains()
    pack = registry.get(code)
    if pack is None:
        raise HTTPException(status_code=404, detail="domain not found")
    return _pack_to_api(pack)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_domain(payload: DomainIn) -> dict:
    registry = get_domains()
    if registry.get(payload.code):
        raise HTTPException(status_code=409, detail="domain already exists")
    path = registry.domains_dir / f"{payload.code}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml_dump(payload.model_dump()), encoding="utf-8")
    registry.reload()
    logger.info("domain.created", code=payload.code, source_path=str(path))
    pack = registry.get(payload.code)
    if pack is None:
        raise HTTPException(status_code=500, detail="failed to reload registry")
    return _pack_to_api(pack)


@router.put("/{code}")
async def update_domain(code: str, payload: DomainIn) -> dict:
    if code != payload.code:
        raise HTTPException(status_code=400, detail="code in URL does not match body")
    registry = get_domains()
    pack = registry.get(code)
    if pack is None:
        raise HTTPException(status_code=404, detail="domain not found")
    path = pack.source_path or (registry.domains_dir / f"{code}.yaml")
    path.write_text(_yaml_dump(payload.model_dump()), encoding="utf-8")
    registry.reload()
    logger.info("domain.updated", code=code, source_path=str(path))
    updated = registry.get(code)
    assert updated is not None
    return _pack_to_api(updated)


@router.put("/{code}/yaml")
async def update_domain_yaml(code: str, payload: DomainYamlIn) -> dict:
    """Write raw YAML directly — for the admin YAML editor screen."""
    try:
        data = yaml.safe_load(payload.yaml) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"invalid yaml: {exc}") from exc
    if not isinstance(data, dict) or data.get("code") != code:
        raise HTTPException(status_code=400, detail="yaml must contain matching code")
    registry = get_domains()
    path = registry.domains_dir / f"{code}.yaml"
    path.write_text(payload.yaml, encoding="utf-8")
    registry.reload()
    pack = registry.get(code)
    if pack is None:
        raise HTTPException(status_code=400, detail="reload failed — yaml invalid?")
    logger.info("domain.yaml_updated", code=code, source_path=str(path))
    return _pack_to_api(pack)


@router.post("/generate")
async def generate_domain(payload: DomainGenerateIn) -> dict:
    """Ask Gemma 4 to scaffold a new domain pack from a natural-language
    description. Does NOT persist — returns the generated YAML and
    structured fields so the admin can review and save."""
    if len(payload.description.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="description must be at least 10 characters",
        )
    result = await generate_domain_from_description(
        payload.description,
        model=payload.model,
    )
    if result.error:
        raise HTTPException(status_code=502, detail=f"LLM error: {result.error}")
    payload_dict = {
        "code": result.code or "new_domain",
        "display_name": result.display_name or "New domain",
        "description": result.description or "",
        "vocabulary": result.vocabulary,
        "required_documents": result.required_documents,
        "rule_module": result.rule_module or result.code or "new_domain",
        "decision_prompt_snippet": result.decision_prompt_snippet,
        "thresholds": result.thresholds,
    }
    logger.info(
        "domain.generate",
        proposed_code=result.code,
        proposed_display_name=result.display_name,
    )
    return {
        "proposal": payload_dict,
        "yaml": _yaml_dump(payload_dict),
        "raw_response": result.raw_response,
    }


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(code: str) -> None:
    registry = get_domains()
    pack = registry.get(code)
    if pack is None:
        raise HTTPException(status_code=404, detail="domain not found")
    path = pack.source_path
    if path and path.exists():
        path.unlink()
    registry.reload()
    logger.info("domain.deleted", code=code)


def _pack_to_api(pack: DomainPack) -> dict:
    d = pack.to_dict()
    # Add the raw YAML so the admin editor can round-trip faithfully.
    if pack.source_path and pack.source_path.exists():
        d["yaml"] = pack.source_path.read_text(encoding="utf-8")
    else:
        d["yaml"] = _yaml_dump(pack.to_dict())
    return d


def _yaml_dump(data: dict) -> str:
    return yaml.safe_dump(
        {k: v for k, v in data.items() if k not in {"source_path", "yaml"}},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
