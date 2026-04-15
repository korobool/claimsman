"""LLM-based field extraction via a locally-running Ollama + Gemma 4.

Claimsman never talks to OpenAI or Gemini (spec §7.2). All extraction
goes to the Ollama instance already running on the dev host. The model
is multimodal and receives both the page image (base64) and the OCR
text, together with a schema description and a domain context.

Response shape is a dict keyed by schema field names. We ask the model
for strict JSON and parse defensively — Gemma 4 is usually well-behaved
but we allow a single fenced block or the whole response.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from packages.schemas import DomainPack, SchemaDef, get_domains, get_schemas

DEFAULT_OLLAMA = os.environ.get("CLAIMSMAN_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("CLAIMSMAN_OLLAMA_DEFAULT_MODEL", "gemma4:31b")
DEFAULT_TIMEOUT = float(os.environ.get("CLAIMSMAN_OLLAMA_TIMEOUT", "300"))


@dataclass
class ExtractionResult:
    doc_type: str
    domain: str
    fields: dict[str, Any]
    model: str
    raw_response: str
    vision_used: bool
    error: Optional[str] = None
    all_schema_fields: list[str] = field(default_factory=list)


class OllamaExtractor:
    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA,
        default_model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout
        self._lock = threading.Lock()

    async def extract(
        self,
        *,
        doc_type: str,
        domain_code: str,
        ocr_text: str,
        image_paths: list[Path] | None = None,
        model: Optional[str] = None,
    ) -> ExtractionResult:
        schemas = get_schemas()
        domains = get_domains()
        schema = schemas.get(doc_type) or schemas.get("unknown")
        if schema is None:
            return ExtractionResult(
                doc_type=doc_type,
                domain=domain_code,
                fields={},
                model=model or self.default_model,
                raw_response="",
                vision_used=False,
                error=f"no schema for doc_type {doc_type!r}",
            )
        domain = domains.get(domain_code)
        if domain is None:
            return ExtractionResult(
                doc_type=doc_type,
                domain=domain_code,
                fields={},
                model=model or self.default_model,
                raw_response="",
                vision_used=False,
                error=f"no domain for code {domain_code!r}",
            )

        effective_model = model or self.default_model
        system_prompt = _build_system_prompt(schema, domain)
        user_prompt = _build_user_prompt(schema, ocr_text)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        images_b64: list[str] = []
        if image_paths:
            for p in image_paths[:4]:  # cap to keep prompt size bounded
                try:
                    images_b64.append(_encode_image(p))
                except Exception:  # noqa: BLE001
                    pass
        if images_b64:
            messages[-1]["images"] = images_b64

        payload = {
            "model": effective_model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
            },
            "keep_alive": "30m",
            "think": False,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ExtractionResult(
                doc_type=doc_type,
                domain=domain_code,
                fields={},
                model=effective_model,
                raw_response="",
                vision_used=bool(images_b64),
                error=f"{type(exc).__name__}: {exc}",
                all_schema_fields=[f.name for f in schema.fields],
            )

        raw = _extract_message_content(data)
        fields = _parse_fields(raw, schema)
        return ExtractionResult(
            doc_type=doc_type,
            domain=domain_code,
            fields=fields,
            model=effective_model,
            raw_response=raw[:4000],
            vision_used=bool(images_b64),
            all_schema_fields=[f.name for f in schema.fields],
        )


def _encode_image(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _build_system_prompt(schema: SchemaDef, domain: DomainPack) -> str:
    preamble = (schema.llm_hints or {}).get("system_preamble") or ""
    parts: list[str] = [
        "You are Claimsman, an insurance claims-understanding assistant.",
        f"You are extracting structured fields from a {schema.display_name} "
        f"for the {domain.display_name} domain.",
        "",
        "Domain context:",
        domain.description.strip(),
    ]
    if domain.vocabulary:
        parts.append("")
        parts.append("Domain vocabulary (reference only):")
        for key, value in domain.vocabulary.items():
            parts.append(f"- {key}: {value}")
    if preamble:
        parts.append("")
        parts.append("Doc-type hint:")
        parts.append(preamble.strip())
    parts.append("")
    parts.append(
        "Respond with a single JSON object. Keys MUST match the schema "
        "field names exactly. Do not invent fields. If a value is not "
        "present in the document, use null. Keep free text in the "
        "original language of the document."
    )
    return "\n".join(parts)


def _build_user_prompt(schema: SchemaDef, ocr_text: str) -> str:
    lines: list[str] = [
        f"Document type: {schema.doc_type}",
        f"Description: {schema.description.strip()}",
        "",
        "Fields to extract:",
    ]
    for f in schema.fields:
        req = " [required]" if f.required else ""
        desc = f" — {f.description}" if f.description else ""
        lines.append(f"  - {f.name} ({f.type}){req}{desc}")
        if f.fields:
            for sub in f.fields:
                sub_desc = f" — {sub.description}" if sub.description else ""
                lines.append(f"      - {sub.name} ({sub.type}){sub_desc}")
    lines.append("")
    lines.append("OCR text (use as primary source; the image is attached for cross-reference):")
    lines.append("---")
    lines.append((ocr_text or "").strip()[:6000] or "(no OCR text available)")
    lines.append("---")
    lines.append("")
    lines.append(
        'Return ONLY valid JSON in the shape: {"field_name": value, ...}. '
        "For list-typed fields return a JSON array."
    )
    return "\n".join(lines)


def _extract_message_content(data: dict) -> str:
    # Ollama /api/chat non-streaming: {"message": {"role":"assistant","content":"..."}}
    msg = data.get("message") if isinstance(data, dict) else None
    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        return msg["content"]
    return data.get("response", "") if isinstance(data, dict) else ""


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _parse_fields(raw: str, schema: SchemaDef) -> dict[str, Any]:
    if not raw:
        return {}
    # try straight JSON first (format=json should guarantee this)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return _restrict_to_schema(parsed, schema)
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            return _restrict_to_schema(parsed[0], schema)
    except Exception:  # noqa: BLE001
        pass
    # try fenced block
    match = _JSON_BLOCK.search(raw)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return _restrict_to_schema(parsed, schema)
        except Exception:  # noqa: BLE001
            pass
    # last ditch: find the first {...} and try
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return _restrict_to_schema(parsed, schema)
        except Exception:  # noqa: BLE001
            pass
    return {}


def _restrict_to_schema(data: dict, schema: SchemaDef) -> dict[str, Any]:
    allowed = {f.name for f in schema.fields}
    return {k: v for k, v in data.items() if k in allowed}


_extractor: Optional[OllamaExtractor] = None
_extractor_lock = threading.Lock()


def get_extractor() -> OllamaExtractor:
    global _extractor
    if _extractor is None:
        with _extractor_lock:
            if _extractor is None:
                _extractor = OllamaExtractor()
    return _extractor
