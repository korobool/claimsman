"""Load document schemas and domain packs from YAML files.

The registries are file-backed and hot-reloadable: calling
``reload()`` rescans the config directories. Both schemas and domains
are plain Python dataclasses so they can round-trip through JSON.
"""
from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

_DEFAULT_CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"
CONFIG_ROOT = Path(os.environ.get("CLAIMSMAN_CONFIG_ROOT") or _DEFAULT_CONFIG_ROOT)
SCHEMAS_DIR = CONFIG_ROOT / "schemas"
DOMAINS_DIR = CONFIG_ROOT / "domains"


@dataclass
class FieldDef:
    name: str
    label: Optional[str] = None
    type: str = "text"
    required: bool = False
    description: Optional[str] = None
    fields: list["FieldDef"] = field(default_factory=list)  # for object/list[object]

    @classmethod
    def from_dict(cls, data: dict) -> "FieldDef":
        return cls(
            name=data["name"],
            label=data.get("label"),
            type=str(data.get("type", "text")),
            required=bool(data.get("required", False)),
            description=data.get("description"),
            fields=[cls.from_dict(f) for f in (data.get("fields") or [])],
        )


@dataclass
class SchemaDef:
    doc_type: str
    display_name: str
    domains: list[str]
    description: str
    fields: list[FieldDef]
    llm_hints: dict[str, Any] = field(default_factory=dict)
    validation: list[dict[str, Any]] = field(default_factory=list)
    source_path: Optional[Path] = None

    def field_map(self) -> dict[str, FieldDef]:
        return {f.name: f for f in self.fields}

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.source_path:
            d["source_path"] = str(self.source_path)
        return d


@dataclass
class DomainPack:
    code: str
    display_name: str
    description: str
    vocabulary: dict[str, Any]
    required_documents: list[dict[str, list[str]]]
    rule_module: str
    decision_prompt_snippet: str
    thresholds: dict[str, Any]
    source_path: Optional[Path] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.source_path:
            d["source_path"] = str(self.source_path)
        return d


class SchemaRegistry:
    def __init__(self, schemas_dir: Path = SCHEMAS_DIR) -> None:
        self.schemas_dir = schemas_dir
        self._by_doc_type: dict[str, SchemaDef] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._by_doc_type = {}
            if not self.schemas_dir.exists():
                return
            for path in sorted(self.schemas_dir.glob("*.yaml")):
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(data, dict) or "doc_type" not in data:
                    continue
                schema = SchemaDef(
                    doc_type=data["doc_type"],
                    display_name=data.get("display_name") or data["doc_type"],
                    domains=list(data.get("domains") or []),
                    description=data.get("description") or "",
                    fields=[FieldDef.from_dict(f) for f in (data.get("fields") or [])],
                    llm_hints=dict(data.get("llm_hints") or {}),
                    validation=list(data.get("validation") or []),
                    source_path=path,
                )
                self._by_doc_type[schema.doc_type] = schema

    def get(self, doc_type: str) -> Optional[SchemaDef]:
        return self._by_doc_type.get(doc_type) or self._by_doc_type.get("unknown")

    def all(self) -> list[SchemaDef]:
        return list(self._by_doc_type.values())

    def doc_types(self) -> list[str]:
        return list(self._by_doc_type.keys())


class DomainRegistry:
    def __init__(self, domains_dir: Path = DOMAINS_DIR) -> None:
        self.domains_dir = domains_dir
        self._by_code: dict[str, DomainPack] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self._by_code = {}
            if not self.domains_dir.exists():
                return
            for path in sorted(self.domains_dir.glob("*.yaml")):
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(data, dict) or "code" not in data:
                    continue
                pack = DomainPack(
                    code=data["code"],
                    display_name=data.get("display_name") or data["code"],
                    description=data.get("description") or "",
                    vocabulary=dict(data.get("vocabulary") or {}),
                    required_documents=list(data.get("required_documents") or []),
                    rule_module=data.get("rule_module") or data["code"],
                    decision_prompt_snippet=data.get("decision_prompt_snippet") or "",
                    thresholds=dict(data.get("thresholds") or {}),
                    source_path=path,
                )
                self._by_code[pack.code] = pack

    def get(self, code: str) -> Optional[DomainPack]:
        return self._by_code.get(code)

    def all(self) -> list[DomainPack]:
        return list(self._by_code.values())

    def codes(self) -> list[str]:
        return list(self._by_code.keys())


_schemas: Optional[SchemaRegistry] = None
_domains: Optional[DomainRegistry] = None
_init_lock = threading.Lock()


def get_schemas() -> SchemaRegistry:
    global _schemas
    if _schemas is None:
        with _init_lock:
            if _schemas is None:
                _schemas = SchemaRegistry()
    return _schemas


def get_domains() -> DomainRegistry:
    global _domains
    if _domains is None:
        with _init_lock:
            if _domains is None:
                _domains = DomainRegistry()
    return _domains
