"""Unit tests for the JSON parsers inside the extract package. The
extraction and decide wrappers don't actually call Ollama here — we
just exercise the pure helper functions that turn raw LLM text into
structured Python dicts, plus the 'restrict to schema' guard."""
from dataclasses import dataclass
from typing import Any

from packages.extract.decide import _normalize, _parse_decision
from packages.extract.generators import _as_dict, _as_list, _parse_json
from packages.extract.ollama import _parse_fields, _restrict_to_schema


# --- fake schema stub ---------------------------------------------------


@dataclass
class _Field:
    name: str


@dataclass
class _Schema:
    fields: list


def _schema(field_names: list[str]) -> _Schema:
    return _Schema(fields=[_Field(name=n) for n in field_names])


# --- _parse_fields + _restrict_to_schema --------------------------------


def test_parse_fields_plain_json() -> None:
    raw = '{"a": 1, "b": "two"}'
    schema = _schema(["a", "b"])
    assert _parse_fields(raw, schema) == {"a": 1, "b": "two"}


def test_parse_fields_fenced_json() -> None:
    raw = '```json\n{"a": 1}\n```'
    schema = _schema(["a"])
    assert _parse_fields(raw, schema) == {"a": 1}


def test_parse_fields_strips_unknown_keys() -> None:
    raw = '{"a": 1, "hallucinated": "nope"}'
    schema = _schema(["a"])
    assert _parse_fields(raw, schema) == {"a": 1}


def test_parse_fields_returns_empty_on_garbage() -> None:
    assert _parse_fields("", _schema(["a"])) == {}
    assert _parse_fields("not even close to json", _schema(["a"])) == {}


def test_restrict_to_schema_drops_extra() -> None:
    data: dict[str, Any] = {"a": 1, "b": 2, "c": 3}
    schema = _schema(["a", "c"])
    assert _restrict_to_schema(data, schema) == {"a": 1, "c": 3}


# --- _parse_decision + _normalize ---------------------------------------


def test_parse_decision_plain_json() -> None:
    raw = '{"outcome": "approve", "amount": 100, "currency": "EUR", "confidence": 0.9, "rationale": "ok"}'
    parsed = _parse_decision(raw)
    assert parsed["outcome"] == "approve"
    assert parsed["amount"] == 100
    assert parsed["currency"] == "EUR"
    assert parsed["confidence"] == 0.9


def test_parse_decision_invalid_outcome_becomes_needs_info() -> None:
    raw = '{"outcome": "YOLO", "amount": 1, "rationale": "nope"}'
    parsed = _parse_decision(raw)
    assert parsed["outcome"] == "needs_info"


def test_parse_decision_with_string_amount() -> None:
    raw = '{"outcome": "approve", "amount": "42.50", "rationale": "ok"}'
    parsed = _parse_decision(raw)
    assert parsed["amount"] == 42.50


def test_parse_decision_fenced_json() -> None:
    raw = '```json\n{"outcome": "deny", "rationale": "no coverage"}\n```'
    parsed = _parse_decision(raw)
    assert parsed["outcome"] == "deny"


def test_normalize_outcome_with_dashes_or_spaces() -> None:
    assert _normalize({"outcome": "partial-approve"})["outcome"] == "partial_approve"
    assert _normalize({"outcome": "NEEDS INFO"})["outcome"] == "needs_info"


# --- generators _parse_json / _as_dict / _as_list -----------------------


def test_parse_json_handles_plain_and_fenced() -> None:
    assert _parse_json('{"a":1}') == {"a": 1}
    assert _parse_json('```json\n{"a":1}\n```') == {"a": 1}
    assert _parse_json("not json") == {}


def test_as_dict_and_as_list_guards() -> None:
    assert _as_dict({"x": 1}) == {"x": 1}
    assert _as_dict("string") == {}
    assert _as_dict(None) == {}
    assert _as_list([1, 2, 3]) == [1, 2, 3]
    assert _as_list("string") == []
    assert _as_list({}) == []
