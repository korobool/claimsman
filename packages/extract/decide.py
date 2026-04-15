"""LLM-based decision proposer.

Given a claim summary (domain + claimant + findings + extracted-fields
per document), ask Gemma 4 to return a structured decision:

    {
      "outcome": "approve" | "partial_approve" | "deny" | "needs_info",
      "amount": float | null,
      "currency": str | null,
      "confidence": float,     # 0-1, model's own confidence
      "rationale": "markdown text"
    }

The wrapper lives alongside the extraction wrapper because both use the
same Ollama client and keep_alive semantics.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from packages.schemas import DomainPack, get_domains

DEFAULT_OLLAMA = os.environ.get("CLAIMSMAN_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("CLAIMSMAN_OLLAMA_DEFAULT_MODEL", "gemma4:31b")
DEFAULT_TIMEOUT = float(os.environ.get("CLAIMSMAN_OLLAMA_TIMEOUT", "300"))


ALLOWED_OUTCOMES = ("approve", "partial_approve", "deny", "needs_info")


@dataclass
class DecisionProposal:
    outcome: str
    amount: Optional[float]
    currency: Optional[str]
    confidence: float
    rationale: str
    raw_response: str
    model: str
    error: Optional[str] = None


async def propose_decision(
    *,
    domain_code: str,
    claim_summary: dict[str, Any],
    model: Optional[str] = None,
    base_url: str = DEFAULT_OLLAMA,
    timeout: float = DEFAULT_TIMEOUT,
) -> DecisionProposal:
    effective_model = model or DEFAULT_MODEL
    domain = get_domains().get(domain_code)
    if domain is None:
        return DecisionProposal(
            outcome="needs_info",
            amount=None,
            currency=None,
            confidence=0.0,
            rationale=f"unknown domain {domain_code!r}; defaulting to needs_info.",
            raw_response="",
            model=effective_model,
            error="unknown domain",
        )

    system_prompt = _build_system_prompt(domain)
    user_prompt = _build_user_prompt(claim_summary)

    payload = {
        "model": effective_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "top_p": 0.9},
        "keep_alive": "30m",
        "think": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return DecisionProposal(
            outcome="needs_info",
            amount=None,
            currency=None,
            confidence=0.0,
            rationale="",
            raw_response="",
            model=effective_model,
            error=f"{type(exc).__name__}: {exc}",
        )

    raw = _extract_message_content(data)
    parsed = _parse_decision(raw)
    return DecisionProposal(
        outcome=parsed.get("outcome", "needs_info"),
        amount=parsed.get("amount"),
        currency=parsed.get("currency"),
        confidence=float(parsed.get("confidence") or 0.0),
        rationale=str(parsed.get("rationale") or ""),
        raw_response=raw[:4000],
        model=effective_model,
    )


def _build_system_prompt(domain: DomainPack) -> str:
    parts = [
        "You are Claimsman, a claims-adjudication reasoning assistant.",
        f"You are reviewing a {domain.display_name} claim.",
        "",
        "Domain context:",
        domain.description.strip(),
    ]
    if domain.decision_prompt_snippet:
        parts.append("")
        parts.append("Decisioning guidance:")
        parts.append(domain.decision_prompt_snippet.strip())
    parts.append("")
    parts.append(
        "Propose a decision. Respond with ONE JSON object with exactly these "
        'keys: "outcome", "amount", "currency", "confidence", "rationale". '
        'outcome MUST be one of: "approve", "partial_approve", "deny", "needs_info". '
        "amount is a number or null. confidence is 0-1. rationale is "
        "concise markdown, a few short sentences, citing specific findings "
        "or documents. Do NOT wrap the JSON in a code fence."
    )
    return "\n".join(parts)


def _build_user_prompt(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2)


def _extract_message_content(data: dict) -> str:
    msg = data.get("message") if isinstance(data, dict) else None
    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
        return msg["content"]
    return data.get("response", "") if isinstance(data, dict) else ""


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_decision(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return _normalize(parsed)
    except Exception:  # noqa: BLE001
        pass
    m = _JSON_BLOCK.search(raw)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                return _normalize(parsed)
        except Exception:  # noqa: BLE001
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return _normalize(parsed)
        except Exception:  # noqa: BLE001
            pass
    return {}


def _normalize(data: dict) -> dict[str, Any]:
    outcome = str(data.get("outcome") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if outcome not in ALLOWED_OUTCOMES:
        outcome = "needs_info"
    amount = data.get("amount")
    if isinstance(amount, str):
        try:
            amount = float(amount.replace(",", ""))
        except ValueError:
            amount = None
    return {
        "outcome": outcome,
        "amount": amount if isinstance(amount, (int, float)) else None,
        "currency": data.get("currency") if isinstance(data.get("currency"), str) else None,
        "confidence": float(data.get("confidence") or 0.0),
        "rationale": str(data.get("rationale") or ""),
    }
