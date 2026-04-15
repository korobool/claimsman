"""Health-insurance rule module.

Every rule is a pure function that takes a ClaimContext and returns a
list of RuleFinding. They run synchronously in the analyze stage.
"""
from __future__ import annotations

from config.domain_rules.common import (
    ClaimContext,
    RuleFinding,
    RuleFn,
    names_match,
    parse_amount,
    parse_date,
    sum_line_items,
)


def check_required_documents(ctx: ClaimContext) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    clinical_types = {"prescription", "medical_report", "discharge_summary"}
    financial_types = {"receipt", "invoice"}
    has_clinical = any(d.doc_type in clinical_types for d in ctx.documents)
    has_financial = any(d.doc_type in financial_types for d in ctx.documents)
    if not has_clinical:
        findings.append(
            RuleFinding(
                severity="error",
                code="missing_required_doc",
                message=(
                    "A health-insurance claim needs at least one clinical "
                    "document: prescription, medical_report, or discharge_summary."
                ),
                refs={"missing_any_of": sorted(clinical_types)},
            )
        )
    if not has_financial:
        findings.append(
            RuleFinding(
                severity="error",
                code="missing_required_doc",
                message=(
                    "A health-insurance claim needs a proof of payment: "
                    "a receipt or an invoice."
                ),
                refs={"missing_any_of": sorted(financial_types)},
            )
        )
    return findings


def check_patient_name_consistency(ctx: ClaimContext) -> list[RuleFinding]:
    names = []
    for doc in ctx.documents:
        name = doc.fields.get("patient_name") or doc.fields.get("member_name")
        if isinstance(name, str) and name.strip():
            names.append((doc, name.strip()))
    if len(names) < 2:
        return []
    max_dist = int(ctx.thresholds.get("name_levenshtein_max", 2) or 2)
    ref_doc, ref_name = names[0]
    findings: list[RuleFinding] = []
    for doc, name in names[1:]:
        if not names_match(ref_name, name, max_distance=max_dist):
            findings.append(
                RuleFinding(
                    severity="warning",
                    code="name_mismatch",
                    message=(
                        f"Patient name on {doc.display_name or doc.doc_type} "
                        f"({name!r}) does not match the name on "
                        f"{ref_doc.display_name or ref_doc.doc_type} ({ref_name!r})."
                    ),
                    refs={
                        "reference_document_id": ref_doc.id,
                        "other_document_id": doc.id,
                        "left": ref_name,
                        "right": name,
                    },
                )
            )
    return findings


def check_totals_match_line_items(ctx: ClaimContext) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    tolerance = float(ctx.thresholds.get("amount_tolerance", 0.02) or 0.02)
    for doc in ctx.of_type("receipt", "invoice"):
        total = parse_amount(doc.fields.get("total"))
        line_sum = sum_line_items(doc.fields.get("line_items"), key="total")
        if total is None or line_sum is None:
            continue
        diff = abs(total - line_sum)
        if total > 0 and diff / total > tolerance:
            findings.append(
                RuleFinding(
                    severity="error",
                    code="amount_mismatch",
                    message=(
                        f"Sum of line items on "
                        f"{doc.display_name or doc.doc_type} ({line_sum:.2f}) "
                        f"does not match the grand total ({total:.2f})."
                    ),
                    refs={"document_id": doc.id, "total": total, "line_sum": line_sum},
                )
            )
    return findings


def check_treatment_within_issue_window(ctx: ClaimContext) -> list[RuleFinding]:
    """If we have both a clinical visit date and a receipt date, flag
    receipts issued more than 90 days away from the visit date."""
    visit_dates: list = []
    for doc in ctx.of_type("medical_report", "discharge_summary", "prescription"):
        d = (
            parse_date(doc.fields.get("visit_date"))
            or parse_date(doc.fields.get("discharge_date"))
            or parse_date(doc.fields.get("issue_date"))
        )
        if d:
            visit_dates.append((doc, d))
    if not visit_dates:
        return []
    findings: list[RuleFinding] = []
    for doc in ctx.of_type("receipt", "invoice"):
        d = parse_date(doc.fields.get("issue_date"))
        if not d:
            continue
        closest = min(visit_dates, key=lambda x: abs((x[1] - d).days))
        delta_days = abs((closest[1] - d).days)
        if delta_days > 90:
            findings.append(
                RuleFinding(
                    severity="warning",
                    code="date_out_of_window",
                    message=(
                        f"Receipt/invoice {doc.display_name or doc.doc_type} "
                        f"was issued {delta_days} days away from the nearest "
                        "clinical visit date — confirm this is the same episode of care."
                    ),
                    refs={
                        "document_id": doc.id,
                        "clinical_document_id": closest[0].id,
                        "delta_days": delta_days,
                    },
                )
            )
    return findings


def check_diagnoses_present(ctx: ClaimContext) -> list[RuleFinding]:
    clinical = ctx.of_type("medical_report", "discharge_summary")
    if not clinical:
        return []
    for doc in clinical:
        diag = doc.fields.get("diagnoses")
        if isinstance(diag, list) and diag:
            return []
    return [
        RuleFinding(
            severity="warning",
            code="no_diagnosis",
            message=(
                "No diagnosis entries were extracted from the clinical "
                "documents. A reviewer should verify that the medical "
                "necessity is clear from the documents."
            ),
        )
    ]


RULES: list[RuleFn] = [
    check_required_documents,
    check_patient_name_consistency,
    check_totals_match_line_items,
    check_treatment_within_issue_window,
    check_diagnoses_present,
]
