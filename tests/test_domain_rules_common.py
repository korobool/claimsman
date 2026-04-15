"""Unit tests for the shared domain-rule helpers in
``config/domain_rules/common.py``. These are pure Python functions
with no external deps so they run fast and deterministically.
"""
from datetime import date

from config.domain_rules.common import (
    ClaimContext,
    DocumentView,
    names_match,
    parse_amount,
    parse_date,
    sum_line_items,
)


# --- parse_date ----------------------------------------------------------


def test_parse_date_iso() -> None:
    assert parse_date("2025-12-01") == date(2025, 12, 1)


def test_parse_date_european_dots() -> None:
    assert parse_date("01.12.2025") == date(2025, 12, 1)


def test_parse_date_european_slashes() -> None:
    assert parse_date("01/12/2025") == date(2025, 12, 1)


def test_parse_date_passthrough_date_object() -> None:
    d = date(2024, 6, 15)
    assert parse_date(d) == d


def test_parse_date_returns_none_on_garbage() -> None:
    assert parse_date("not a date") is None
    assert parse_date(None) is None
    assert parse_date("") is None


# --- parse_amount --------------------------------------------------------


def test_parse_amount_plain_number() -> None:
    assert parse_amount(18.20) == 18.20
    assert parse_amount("18.20") == 18.20


def test_parse_amount_european_decimal_comma() -> None:
    assert parse_amount("27,19") == 27.19


def test_parse_amount_bulgarian_currency_suffix() -> None:
    assert parse_amount("18.20 лв") == 18.20
    assert parse_amount("1 234,56 лв") == 1234.56


def test_parse_amount_euro_symbol() -> None:
    assert parse_amount("€ 42.50") == 42.50


def test_parse_amount_returns_none_on_garbage() -> None:
    assert parse_amount("abc") is None
    assert parse_amount(None) is None


# --- sum_line_items ------------------------------------------------------


def test_sum_line_items_simple() -> None:
    items = [
        {"description": "a", "total": 10.0},
        {"description": "b", "total": 20.0},
    ]
    assert sum_line_items(items) == 30.0


def test_sum_line_items_missing_total() -> None:
    items = [
        {"description": "a", "total": 10.0},
        {"description": "b"},  # no total
    ]
    assert sum_line_items(items) == 10.0


def test_sum_line_items_empty_returns_none() -> None:
    assert sum_line_items([]) is None
    assert sum_line_items(None) is None
    assert sum_line_items("not a list") is None


# --- names_match (Levenshtein) ------------------------------------------


def test_names_match_exact() -> None:
    assert names_match("John Smith", "John Smith") is True


def test_names_match_case_insensitive() -> None:
    assert names_match("john smith", "JOHN SMITH") is True


def test_names_match_whitespace_normalized() -> None:
    assert names_match("John  Smith", "John Smith") is True


def test_names_match_typo_within_threshold() -> None:
    assert names_match("John Smith", "Jhon Smith", max_distance=2) is True


def test_names_match_typo_outside_threshold() -> None:
    assert names_match("John Smith", "Mary Jones", max_distance=2) is False


def test_names_match_empty() -> None:
    assert names_match("", "John") is False
    assert names_match(None, "John") is False


# --- ClaimContext / DocumentView -----------------------------------------


def test_claim_context_of_type_and_first_of() -> None:
    docs = [
        DocumentView(id="d1", doc_type="receipt", display_name="r.pdf", fields={}),
        DocumentView(id="d2", doc_type="prescription", display_name="rx.pdf", fields={}),
        DocumentView(id="d3", doc_type="receipt", display_name="r2.pdf", fields={}),
    ]
    ctx = ClaimContext(
        claim_id="c1",
        claim_code="CLM-1",
        domain="health_insurance",
        claimant_name=None,
        policy_number=None,
        documents=docs,
    )
    receipts = ctx.of_type("receipt")
    assert len(receipts) == 2
    assert ctx.first_of("prescription") is docs[1]
    assert ctx.first_of("police_report") is None
