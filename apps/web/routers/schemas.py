"""Admin CRUD + LLM-assisted generation for document-type schemas.

Schemas live under ``config/schemas/*.yaml`` and are loaded by
``packages.schemas.SchemaRegistry``. This router exposes read and
generate endpoints; write-through to disk and UI-driven YAML editing
will expand in a later milestone alongside the Schemas admin screen.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from apps.web.logging_setup import logger
from apps.web.services.storage import StorageService
from packages.extract import generate_schema_from_sample
from packages.ingest import ingest_file
from packages.ocr import OcrResult, get_ocr_engine
from packages.schemas import SchemaDef, get_domains, get_schemas

router = APIRouter(prefix="/schemas", tags=["schemas"])


class SchemaYamlIn(BaseModel):
    yaml: str = Field(..., min_length=10)


class SchemaFromTextIn(BaseModel):
    ocr_text: str = Field(..., min_length=20)


@router.get("")
async def list_schemas() -> dict:
    reg = get_schemas()
    return {"schemas": [_schema_to_api(s) for s in reg.all()]}


@router.get("/{doc_type}")
async def get_schema(doc_type: str) -> dict:
    reg = get_schemas()
    schema = reg.get(doc_type)
    if schema is None:
        raise HTTPException(status_code=404, detail="schema not found")
    return _schema_to_api(schema)


@router.put("/{doc_type}/yaml")
async def update_schema_yaml(doc_type: str, payload: SchemaYamlIn) -> dict:
    try:
        data = yaml.safe_load(payload.yaml) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"invalid yaml: {exc}") from exc
    if not isinstance(data, dict) or data.get("doc_type") != doc_type:
        raise HTTPException(status_code=400, detail="yaml must contain matching doc_type")
    reg = get_schemas()
    path = reg.schemas_dir / f"{doc_type}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.yaml, encoding="utf-8")
    reg.reload()
    schema = reg.get(doc_type)
    if schema is None:
        raise HTTPException(status_code=400, detail="reload failed — yaml invalid?")
    logger.info("schema.yaml_updated", doc_type=doc_type, source_path=str(path))
    return _schema_to_api(schema)


@router.post("/generate/from-file")
async def generate_schema_from_file(
    file: Annotated[UploadFile, File(description="Sample document")],
    domain: Annotated[str, Form()] = "health_insurance",
) -> dict:
    """Upload a sample document, run Surya OCR, then ask Gemma 4 to
    propose a new schema. Does NOT persist — returns the proposal for
    admin review."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="sample too large (25 MB max)")

    # Save temporarily under a synthetic claim-id-like hash so we can
    # reuse the normal ingest + ocr paths without touching the claims
    # table.
    sample_id = hashlib.sha256(content).hexdigest()[:16]
    tmp_root = Path("/tmp") / "claimsman-samples" / sample_id
    (tmp_root / "upload").mkdir(parents=True, exist_ok=True)
    src_path = tmp_root / "upload" / (file.filename or "sample.bin")
    src_path.write_bytes(content)

    pages_dir = tmp_root / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    ingested = ingest_file(src_path, pages_dir, mime_hint=file.content_type)

    ocr_text_parts: list[str] = []
    image_paths: list[Path] = []
    engine = get_ocr_engine()
    for p in ingested.pages:
        if p.text_layer:
            ocr_text_parts.append(p.text_layer)
        elif p.image_path:
            image_paths.append(p.image_path)
            try:
                from PIL import Image

                with Image.open(p.image_path) as img:
                    ocr: OcrResult = engine.recognize(img)
                ocr_text_parts.append(ocr.text)
            except Exception as exc:  # noqa: BLE001
                logger.error("schema.generate.ocr_error", error=str(exc))

    ocr_text = "\n".join(ocr_text_parts).strip()
    if not ocr_text:
        raise HTTPException(status_code=422, detail="no text extracted from the sample")

    existing_domains = get_domains().codes()
    gen = await generate_schema_from_sample(
        ocr_text=ocr_text,
        image_paths=image_paths,
        existing_domains=existing_domains,
    )
    if gen.error:
        raise HTTPException(status_code=502, detail=f"LLM error: {gen.error}")

    proposal = {
        "doc_type": gen.doc_type or "new_doc_type",
        "display_name": gen.display_name or "New document type",
        "description": gen.description,
        "domains": gen.domains or [domain],
        "fields": gen.fields,
        "llm_hints": gen.llm_hints,
        "validation": gen.validation,
    }
    logger.info(
        "schema.generate.file",
        filename=file.filename,
        proposed_doc_type=gen.doc_type,
        field_count=len(gen.fields),
    )
    return {
        "proposal": proposal,
        "yaml": yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True, default_flow_style=False),
        "ocr_text_preview": ocr_text[:1000],
        "raw_response": gen.raw_response,
    }


@router.post("/generate/from-text")
async def generate_schema_from_text(payload: SchemaFromTextIn) -> dict:
    existing_domains = get_domains().codes()
    gen = await generate_schema_from_sample(
        ocr_text=payload.ocr_text,
        image_paths=None,
        existing_domains=existing_domains,
    )
    if gen.error:
        raise HTTPException(status_code=502, detail=f"LLM error: {gen.error}")
    proposal = {
        "doc_type": gen.doc_type or "new_doc_type",
        "display_name": gen.display_name or "New document type",
        "description": gen.description,
        "domains": gen.domains or [],
        "fields": gen.fields,
        "llm_hints": gen.llm_hints,
        "validation": gen.validation,
    }
    return {
        "proposal": proposal,
        "yaml": yaml.safe_dump(proposal, sort_keys=False, allow_unicode=True, default_flow_style=False),
        "raw_response": gen.raw_response,
    }


def _schema_to_api(schema: SchemaDef) -> dict:
    d = schema.to_dict()
    if schema.source_path and schema.source_path.exists():
        d["yaml"] = schema.source_path.read_text(encoding="utf-8")
    return d
