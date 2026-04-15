"""Unit tests for the motor-insurance rule module."""
from config.domain_rules.common import ClaimContext, DocumentView
from config.domain_rules.motor_insurance import (
    check_driver_name_vs_policy,
    check_incident_date_vs_repair,
    check_repair_totals,
    check_required_documents,
    check_vin_consistency,
)


def _ctx(documents: list[DocumentView], thresholds: dict | None = None) -> ClaimContext:
    return ClaimContext(
        claim_id="c1",
        claim_code="CLM-1",
        domain="motor_insurance",
        claimant_name=None,
        policy_number=None,
        documents=documents,
        thresholds=thresholds or {},
    )


def test_motor_required_docs_missing_reported() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="repair_estimate", display_name="re.pdf", fields={}),
    ])
    findings = check_required_documents(ctx)
    assert len(findings) >= 2  # missing incident + license + ownership


def test_motor_required_docs_complete_passes() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="police_report", display_name="pr.pdf", fields={}),
        DocumentView(id="d2", doc_type="repair_estimate", display_name="re.pdf", fields={}),
        DocumentView(id="d3", doc_type="driver_license", display_name="dl.pdf", fields={}),
        DocumentView(id="d4", doc_type="insurance_card", display_name="ic.pdf", fields={}),
    ])
    assert check_required_documents(ctx) == []


def test_vin_consistency_matches() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="police_report", display_name="pr.pdf",
                     fields={"vehicles": [{"vin": "1HGBH41JXMN109186"}]}),
        DocumentView(id="d2", doc_type="repair_estimate", display_name="re.pdf",
                     fields={"vehicle": {"vin": "1HGBH41JXMN109186"}}),
    ])
    assert check_vin_consistency(ctx) == []


def test_vin_mismatch_flagged() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="repair_estimate", display_name="re1.pdf",
                     fields={"vehicle": {"vin": "AAAAAAAAAAAAAAAA1"}}),
        DocumentView(id="d2", doc_type="repair_invoice", display_name="re2.pdf",
                     fields={"vehicle": {"vin": "BBBBBBBBBBBBBBBB2"}}),
    ])
    findings = check_vin_consistency(ctx)
    assert any(f.code == "vin_mismatch" for f in findings)


def test_repair_totals_match() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="repair_estimate", display_name="re.pdf",
            fields={
                "total": 500.0,
                "labor_items": [{"description": "labor1", "total": 300.0}],
                "parts_items": [{"description": "part1", "total": 200.0}],
            },
        ),
    ])
    assert check_repair_totals(ctx) == []


def test_repair_totals_mismatch_flagged() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="repair_estimate", display_name="re.pdf",
            fields={
                "total": 1000.0,
                "labor_items": [{"description": "labor1", "total": 300.0}],
                "parts_items": [{"description": "part1", "total": 200.0}],
            },
        ),
    ])
    findings = check_repair_totals(ctx)
    assert any(f.code == "amount_mismatch" for f in findings)


def test_driver_name_vs_policy_match() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="driver_license", display_name="dl.pdf",
                     fields={"full_name": "John Smith"}),
        DocumentView(id="d2", doc_type="insurance_card", display_name="ic.pdf",
                     fields={"member_name": "John Smith"}),
    ])
    assert check_driver_name_vs_policy(ctx) == []


def test_driver_name_vs_policy_mismatch_flagged() -> None:
    ctx = _ctx([
        DocumentView(id="d1", doc_type="driver_license", display_name="dl.pdf",
                     fields={"full_name": "John Smith"}),
        DocumentView(id="d2", doc_type="insurance_card", display_name="ic.pdf",
                     fields={"member_name": "Mary Jones"}),
    ])
    findings = check_driver_name_vs_policy(ctx)
    assert any(f.code == "driver_not_on_policy" for f in findings)


def test_incident_date_before_repair() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="police_report", display_name="pr.pdf",
            fields={"incident_date": "2025-06-01"},
        ),
        DocumentView(
            id="d2", doc_type="repair_estimate", display_name="re.pdf",
            fields={"date": "2025-06-10"},
        ),
    ])
    assert check_incident_date_vs_repair(ctx) == []


def test_repair_before_incident_flagged() -> None:
    ctx = _ctx([
        DocumentView(
            id="d1", doc_type="police_report", display_name="pr.pdf",
            fields={"incident_date": "2025-06-01"},
        ),
        DocumentView(
            id="d2", doc_type="repair_estimate", display_name="re.pdf",
            fields={"date": "2025-05-01"},
        ),
    ])
    findings = check_incident_date_vs_repair(ctx)
    assert any(f.code == "repair_before_incident" for f in findings)
