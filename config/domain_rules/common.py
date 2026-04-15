"""Common helpers used by every domain rule module.

A rule is a plain Python function with the signature

    rule(ctx: ClaimContext) -> list[Finding]

where ``ClaimContext`` is a lightweight view over the assembled claim
(documents, extracted fields, dates, totals). Rules must be pure: no
DB writes, no network calls. Each returned Finding is persisted by the
pipeline runner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Iterable, Optional


@dataclass
class RuleFinding:
    severity: str  # info | warning | error
    code: str
    message: str
    refs: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentView:
    id: str
    doc_type: str
    display_name: Optional[str]
    fields: dict[str, Any]  # flat {schema_key: value}


@dataclass
class ClaimContext:
    claim_id: str
    claim_code: str
    domain: str
    claimant_name: Optional[str]
    policy_number: Optional[str]
    documents: list[DocumentView]
    thresholds: dict[str, Any] = field(default_factory=dict)

    def of_type(self, *doc_types: str) -> list[DocumentView]:
        return [d for d in self.documents if d.doc_type in doc_types]

    def first_of(self, *doc_types: str) -> Optional[DocumentView]:
        for d in self.documents:
            if d.doc_type in doc_types:
                return d
        return None


RuleFn = Callable[[ClaimContext], list[RuleFinding]]


# ---- helpers ----------------------------------------------------------


def parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    # Try a handful of common formats.
    for fmt in (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = (
        str(value)
        .replace("\xa0", "")
        .replace(" ", "")
        .replace("EUR", "")
        .replace("BGN", "")
        .replace("лв.", "")
        .replace("лв", "")
        .replace("$", "")
        .replace("€", "")
        .strip()
    )
    if not s:
        return None
    # European decimals: "1.234,56" → "1234.56"; "27,19" → "27.19"
    if s.count(",") == 1 and s.count(".") >= 1 and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def sum_line_items(items: Any, key: str = "total") -> Optional[float]:
    if not isinstance(items, list):
        return None
    total = 0.0
    any_ok = False
    for it in items:
        if isinstance(it, dict):
            amount = parse_amount(it.get(key))
            if amount is not None:
                total += amount
                any_ok = True
    return total if any_ok else None


def names_match(a: Optional[str], b: Optional[str], max_distance: int = 2) -> bool:
    if not a or not b:
        return False
    a_norm = _normalize_name(a)
    b_norm = _normalize_name(b)
    if a_norm == b_norm:
        return True
    return _levenshtein(a_norm, b_norm) <= max_distance


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]
