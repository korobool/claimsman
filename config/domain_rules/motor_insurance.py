"""Motor-insurance rule module."""
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
    incident_types = {"police_report", "correspondence"}
    repair_types = {"repair_estimate", "repair_invoice"}
    license_types = {"driver_license"}
    ownership_types = {"insurance_card", "vehicle_registration"}
    groups = [
        ("incident report", incident_types),
        ("repair document", repair_types),
        ("driver license", license_types),
        ("insurance card / vehicle registration", ownership_types),
    ]
    for name, types in groups:
        if not any(d.doc_type in types for d in ctx.documents):
            findings.append(
                RuleFinding(
                    severity="error",
                    code="missing_required_doc",
                    message=(
                        f"A motor-insurance claim needs a {name}: one of "
                        f"{sorted(types)} is required."
                    ),
                    refs={"missing_any_of": sorted(types)},
                )
            )
    return findings


def check_vin_consistency(ctx: ClaimContext) -> list[RuleFinding]:
    vins: list[tuple[str, str]] = []
    for doc in ctx.documents:
        vehicle = doc.fields.get("vehicle") if isinstance(doc.fields.get("vehicle"), dict) else None
        vin = None
        if vehicle and isinstance(vehicle.get("vin"), str):
            vin = vehicle["vin"].strip()
        elif isinstance(doc.fields.get("vin"), str):
            vin = doc.fields["vin"].strip()
        if vin:
            vins.append((doc.id, vin))
    if len(vins) < 2:
        return []
    reference = vins[0][1]
    findings: list[RuleFinding] = []
    for doc_id, vin in vins[1:]:
        if vin.upper() != reference.upper():
            findings.append(
                RuleFinding(
                    severity="error",
                    code="vin_mismatch",
                    message=(
                        f"VIN on one document ({vin}) does not match the "
                        f"reference VIN ({reference})."
                    ),
                    refs={"document_id": doc_id, "vin": vin, "reference": reference},
                )
            )
    return findings


def check_repair_totals(ctx: ClaimContext) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    tolerance = float(ctx.thresholds.get("amount_tolerance", 0.05) or 0.05)
    for doc in ctx.of_type("repair_estimate", "repair_invoice"):
        total = parse_amount(doc.fields.get("total"))
        labor_sum = sum_line_items(doc.fields.get("labor_items"))
        parts_sum = sum_line_items(doc.fields.get("parts_items"))
        if total is None:
            continue
        if labor_sum is None and parts_sum is None:
            continue
        computed = (labor_sum or 0.0) + (parts_sum or 0.0)
        diff = abs(total - computed)
        if total > 0 and diff / total > tolerance:
            findings.append(
                RuleFinding(
                    severity="error",
                    code="amount_mismatch",
                    message=(
                        f"Sum of labor+parts on {doc.display_name or doc.doc_type} "
                        f"({computed:.2f}) does not match the grand total ({total:.2f})."
                    ),
                    refs={
                        "document_id": doc.id,
                        "total": total,
                        "computed": computed,
                    },
                )
            )
    return findings


def check_driver_name_vs_policy(ctx: ClaimContext) -> list[RuleFinding]:
    license = ctx.first_of("driver_license")
    card = ctx.first_of("insurance_card")
    if not license or not card:
        return []
    license_name = license.fields.get("full_name")
    member_name = card.fields.get("member_name")
    if not license_name or not member_name:
        return []
    max_dist = int(ctx.thresholds.get("name_levenshtein_max", 2) or 2)
    if not names_match(license_name, member_name, max_distance=max_dist):
        return [
            RuleFinding(
                severity="warning",
                code="driver_not_on_policy",
                message=(
                    f"Driver's license name ({license_name!r}) does not match "
                    f"the policy member name ({member_name!r}). Confirm the "
                    "driver is a named insured on the policy."
                ),
                refs={
                    "license_document_id": license.id,
                    "card_document_id": card.id,
                    "license_name": license_name,
                    "member_name": member_name,
                },
            )
        ]
    return []


def check_incident_date_vs_repair(ctx: ClaimContext) -> list[RuleFinding]:
    incident = ctx.first_of("police_report")
    if incident is None:
        return []
    incident_date = parse_date(incident.fields.get("incident_date")) or parse_date(
        incident.fields.get("report_date")
    )
    if not incident_date:
        return []
    findings: list[RuleFinding] = []
    for doc in ctx.of_type("repair_estimate", "repair_invoice"):
        repair_date = parse_date(doc.fields.get("date"))
        if not repair_date:
            continue
        delta = (repair_date - incident_date).days
        if delta < 0:
            findings.append(
                RuleFinding(
                    severity="error",
                    code="repair_before_incident",
                    message=(
                        f"Repair {doc.display_name or doc.doc_type} is dated "
                        f"{repair_date} — before the incident date "
                        f"{incident_date}."
                    ),
                    refs={"document_id": doc.id, "delta_days": delta},
                )
            )
        elif delta > 365:
            findings.append(
                RuleFinding(
                    severity="warning",
                    code="repair_long_after_incident",
                    message=(
                        f"Repair on {doc.display_name or doc.doc_type} is more "
                        f"than a year after the incident ({delta} days)."
                    ),
                    refs={"document_id": doc.id, "delta_days": delta},
                )
            )
    return findings


RULES: list[RuleFn] = [
    check_required_documents,
    check_vin_consistency,
    check_repair_totals,
    check_driver_name_vs_policy,
    check_incident_date_vs_repair,
]
