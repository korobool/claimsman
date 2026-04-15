"""LLM-assisted generators that help admins create new domains and
document-type schemas. Both use the local Ollama + Gemma 4 endpoint.
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

DEFAULT_OLLAMA = os.environ.get("CLAIMSMAN_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("CLAIMSMAN_OLLAMA_DEFAULT_MODEL", "gemma4:31b")
DEFAULT_TIMEOUT = float(os.environ.get("CLAIMSMAN_OLLAMA_TIMEOUT", "300"))


@dataclass
class GeneratedDomain:
    code: str
    display_name: str
    description: str
    vocabulary: dict
    required_documents: list
    rule_module: str
    decision_prompt_snippet: str
    thresholds: dict
    raw_response: str = ""
    error: Optional[str] = None


@dataclass
class GeneratedSchema:
    doc_type: str
    display_name: str
    description: str
    domains: list[str]
    fields: list[dict]
    llm_hints: dict = field(default_factory=dict)
    validation: list = field(default_factory=list)
    raw_response: str = ""
    error: Optional[str] = None


DOMAIN_SYSTEM_PROMPT = """You are Claimsman, a claims-understanding assistant.
You help administrators scaffold new insurance-claim domain packs.

Given a natural-language description of a business domain, propose a JSON
object with EXACTLY these keys:
  code               snake_case identifier, lowercase, letters/digits/underscore
  display_name       human-readable name
  description        one paragraph
  vocabulary         dict of {category: list[str]} with terms, codes, abbreviations
                     an adjudicator would read in this domain
  required_documents list of {any_of: [doc_type_code, ...]} groups — which kinds
                     of documents a complete claim bundle must contain
  rule_module        the same as code (rule modules are file-backed)
  decision_prompt_snippet   short markdown that describes how a reasonable
                            adjudicator weighs evidence in this domain
  thresholds         {low_confidence: 0.80, amount_tolerance: 0.02, ...}

Output ONLY valid JSON. No code fences, no prose.
"""


SCHEMA_SYSTEM_PROMPT = """You are Claimsman, a claims-understanding assistant.
You help administrators scaffold new document-type schemas from a sample.

Given the OCR text of a sample document (and optionally the page image), propose
a JSON object with EXACTLY these keys:
  doc_type       snake_case identifier
  display_name   human-readable name
  description    one-sentence description
  domains        list of domain codes this doc-type applies to
  fields         list of {name, label, type, required, description} where type
                 is one of: text, date, currency, number, person_name, address,
                 phone, email, list[text], list[object], object
                 For list[object] or object fields, include a nested "fields"
                 array describing sub-fields.
  llm_hints      optional {system_preamble: "..."} to help the extractor
  validation     optional list of validation rule dicts

Keep the schema small and focused: extract real, visible fields from the
sample; do not invent fields that are not in the document.

Output ONLY valid JSON. No code fences, no prose.
"""


async def generate_domain_from_description(
    description: str,
    *,
    model: Optional[str] = None,
    base_url: str = DEFAULT_OLLAMA,
    timeout: float = DEFAULT_TIMEOUT,
) -> GeneratedDomain:
    effective_model = model or DEFAULT_MODEL
    payload = {
        "model": effective_model,
        "messages": [
            {"role": "system", "content": DOMAIN_SYSTEM_PROMPT},
            {"role": "user", "content": description.strip()},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
        "keep_alive": "30m",
        "think": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return GeneratedDomain(
            code="",
            display_name="",
            description="",
            vocabulary={},
            required_documents=[],
            rule_module="",
            decision_prompt_snippet="",
            thresholds={},
            error=f"{type(exc).__name__}: {exc}",
        )
    raw = _content(data)
    parsed = _parse_json(raw)
    return GeneratedDomain(
        code=str(parsed.get("code") or "").strip(),
        display_name=str(parsed.get("display_name") or "").strip(),
        description=str(parsed.get("description") or "").strip(),
        vocabulary=_as_dict(parsed.get("vocabulary")),
        required_documents=_as_list(parsed.get("required_documents")),
        rule_module=str(parsed.get("rule_module") or parsed.get("code") or "").strip(),
        decision_prompt_snippet=str(parsed.get("decision_prompt_snippet") or "").strip(),
        thresholds=_as_dict(parsed.get("thresholds"))
        or {"low_confidence": 0.8, "amount_tolerance": 0.02},
        raw_response=raw[:4000],
    )


async def generate_schema_from_sample(
    *,
    ocr_text: str,
    image_paths: list[Path] | None = None,
    existing_domains: list[str] | None = None,
    model: Optional[str] = None,
    base_url: str = DEFAULT_OLLAMA,
    timeout: float = DEFAULT_TIMEOUT,
) -> GeneratedSchema:
    effective_model = model or DEFAULT_MODEL
    lines: list[str] = []
    if existing_domains:
        lines.append("existing_domains: " + ", ".join(existing_domains))
    lines.append("")
    lines.append("OCR text of the sample document:")
    lines.append("---")
    lines.append((ocr_text or "").strip()[:6000] or "(no OCR text available)")
    lines.append("---")
    user_content = "\n".join(lines)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SCHEMA_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    images_b64: list[str] = []
    if image_paths:
        for p in image_paths[:2]:
            try:
                images_b64.append(base64.b64encode(Path(p).read_bytes()).decode("ascii"))
            except Exception:  # noqa: BLE001
                pass
    if images_b64:
        messages[-1]["images"] = images_b64

    payload = {
        "model": effective_model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
        "keep_alive": "30m",
        "think": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return GeneratedSchema(
            doc_type="",
            display_name="",
            description="",
            domains=[],
            fields=[],
            error=f"{type(exc).__name__}: {exc}",
        )
    raw = _content(data)
    parsed = _parse_json(raw)
    return GeneratedSchema(
        doc_type=str(parsed.get("doc_type") or "").strip(),
        display_name=str(parsed.get("display_name") or "").strip(),
        description=str(parsed.get("description") or "").strip(),
        domains=_as_list(parsed.get("domains")),
        fields=_as_list(parsed.get("fields")),
        llm_hints=_as_dict(parsed.get("llm_hints")),
        validation=_as_list(parsed.get("validation")),
        raw_response=raw[:4000],
    )


# ---- helpers ----------------------------------------------------------


def _content(data: dict) -> str:
    msg = data.get("message") if isinstance(data, dict) else None
    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        return msg["content"]
    return data.get("response", "") if isinstance(data, dict) else ""


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_json(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:  # noqa: BLE001
        pass
    m = _JSON_BLOCK.search(raw)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            pass
    return {}


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []
