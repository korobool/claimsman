"""Unit tests for the health-insurance rule module. Each rule is a
pure function that takes a ClaimContext and returns a list of
RuleFinding, so we build synthetic contexts and assert the findings.
"""
from config.domain_rules.common import ClaimContext, DocumentView
from config.domain_rules.health_insurance import (
    check_diagnoses_present,
    check_patient_name_consistency,
    check_required_documents,
    check_totals_match_line_items,
    check_treatment_within_issue_window,
)


def _ctx(documents: list[DocumentView], thresholds: dict | None = None) -> ClaimContext:
    return ClaimContext(
        claim_id="c1",
        claim_code="CLM-1",
        domain="health_insurance",
        claimant_name=None,
        policy_number=None,
        documents=documents,
        thresholds=thresholds or {},
    )


# --- check_required_documents -------------------------------------------


def test_required_docs_missing_clinical_flagged() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="receipt", display_name="r.pdf", fields={}),
    ])
    findings = check_required_documents(ctx)
    codes = {f.code for f in findings}
    assert "missing_required_doc" in codes
    # missing both clinical AND financial-type-is-OK here → only clinical missing
    assert any("clinical" in f.message or "prescription" in f.message.lower() for f in findings)


def test_required_docs_missing_financial_flagged() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="prescription", display_name="rx.pdf", fields={}),
    ])
    findings = check_required_documents(ctx)
    messages = [f.message for f in findings]
    assert any("receipt" in m or "invoice" in m for m in messages)


def test_required_docs_complete_bundle_passes() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="prescription", display_name="rx.pdf", fields={}),
        DocumentView(id="d2", doc_type="receipt", display_name="r.pdf", fields={}),
    ])
    findings = check_required_documents(ctx)
    assert findings == []


# --- check_patient_name_consistency -------------------------------------


def test_patient_name_consistency_all_match_no_findings() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="prescription", display_name="rx.pdf",
            fields={"patient_name": "John Smith"},
        ),
        DocumentView(
            id="d2", doc_type="receipt", display_name="r.pdf",
            fields={"patient_name": "John Smith"},
        ),
    ])
    assert check_patient_name_consistency(ctx) == []


def test_patient_name_consistency_mismatch_flagged() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="prescription", display_name="rx.pdf",
            fields={"patient_name": "John Smith"},
        ),
        DocumentView(
            id="d2", doc_type="receipt", display_name="r.pdf",
            fields={"patient_name": "Mary Jones"},
        ),
    ])
    findings = check_patient_name_consistency(ctx)
    assert any(f.code == "name_mismatch" for f in findings)


def test_patient_name_consistency_typo_within_threshold() -> None:
    ctx = _ctx(
        [
            DocumentView(
                id="d1", doc_type="prescription", display_name="rx.pdf",
                fields={"patient_name": "John Smith"},
            ),
            DocumentView(
                id="d2", doc_type="receipt", display_name="r.pdf",
                fields={"patient_name": "Jhon Smith"},  # 1-char typo
            ),
        ],
        thresholds={"name_levenshtein_max": 2},
    )
    assert check_patient_name_consistency(ctx) == []


# --- check_totals_match_line_items --------------------------------------


def test_totals_match_clean() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="receipt", display_name="r.pdf",
            fields={
                "total": 30.0,
                "line_items": [
                    {"description": "a", "total": 10.0},
                    {"description": "b", "total": 20.0},
                ],
            },
        ),
    ])
    assert check_totals_match_line_items(ctx) == []


def test_totals_mismatch_flagged() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="receipt", display_name="r.pdf",
            fields={
                "total": 50.0,  # sum says 30
                "line_items": [
                    {"description": "a", "total": 10.0},
                    {"description": "b", "total": 20.0},
                ],
            },
        ),
    ])
    findings = check_totals_match_line_items(ctx)
    assert any(f.code == "amount_mismatch" for f in findings)


def test_totals_match_with_european_decimal() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="receipt", display_name="r.pdf",
            fields={
                "total": "27,19",  # BG format
                "line_items": [
                    {"description": "a", "total": "18.20"},
                    {"description": "b", "total": "8,99"},
                ],
            },
        ),
    ])
    assert check_totals_match_line_items(ctx) == []


# --- check_treatment_within_issue_window --------------------------------


def test_treatment_window_within_90_days() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="medical_report", display_name="mr.pdf",
            fields={"visit_date": "2025-12-01"},
        ),
        DocumentView(
            id="d2", doc_type="receipt", display_name="r.pdf",
            fields={"issue_date": "2025-12-05"},
        ),
    ])
    assert check_treatment_within_issue_window(ctx) == []


def test_treatment_window_outside_90_days() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="medical_report", display_name="mr.pdf",
            fields={"visit_date": "2025-01-01"},
        ),
        DocumentView(
            id="d2", doc_type="receipt", display_name="r.pdf",
            fields={"issue_date": "2025-12-01"},
        ),
    ])
    findings = check_treatment_within_issue_window(ctx)
    assert any(f.code == "date_out_of_window" for f in findings)


# --- check_diagnoses_present --------------------------------------------


def test_diagnoses_present_passes() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="medical_report", display_name="mr.pdf",
            fields={"diagnoses": [{"code": "Z50.8", "description": "rehab"}]},
        ),
    ])
    assert check_diagnoses_present(ctx) == []


def test_diagnoses_missing_flagged() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="medical_report", display_name="mr.pdf",
            fields={},
        ),
    ])
    findings = check_diagnoses_present(ctx)
    assert any(f.code == "no_diagnosis" for f in findings)
