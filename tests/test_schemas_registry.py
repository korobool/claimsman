"""Tests for the schema + domain registry — loads all the real YAML
files from ``config/`` and asserts they parse cleanly with the
expected count of doc types and domains."""
from packages.schemas import get_domains, get_schemas


def test_schemas_registry_loads_all_seeded() -> None:
    reg = get_schemas()
    doc_types = set(reg.doc_types())
    expected = {
        "prescription",
        "receipt",
        "invoice",
        "medical_report",
        "discharge_summary",
        "insurance_card",
        "repair_estimate",
        "repair_invoice",
        "police_report",
        "driver_license",
        "vehicle_registration",
        "photo_of_damage",
        "correspondence",
        "unknown",
    }
    assert expected <= doc_types, f"missing schemas: {expected - doc_types}"


def test_prescription_schema_has_medications_list() -> None:
    schema = get_schemas().get("prescription")
    assert schema is not None
    names = [f.name for f in schema.fields]
    assert "medications" in names
    assert schema.display_name == "Prescription"
    assert "health_insurance" in schema.domains


def test_receipt_schema_has_line_items() -> None:
    schema = get_schemas().get("receipt")
    assert schema is not None
    names = [f.name for f in schema.fields]
    assert "line_items" in names
    assert "total" in names
    assert "currency" in names


def test_domains_registry_loads_both_seeded() -> None:
    reg = get_domains()
    assert "health_insurance" in reg.codes()
    assert "motor_insurance" in reg.codes()


def test_health_domain_has_required_docs_and_rule_module() -> None:
    pack = get_domains().get("health_insurance")
    assert pack is not None
    assert pack.rule_module == "health_insurance"
    assert pack.required_documents  # not empty
    # thresholds has the expected keys
    assert "low_confidence" in pack.thresholds
    assert "amount_tolerance" in pack.thresholds


def test_motor_domain_rule_module() -> None:
    pack = get_domains().get("motor_insurance")
    assert pack is not None
    assert pack.rule_module == "motor_insurance"
    assert pack.vocabulary  # not empty


def test_unknown_schema_is_fallback() -> None:
    reg = get_schemas()
    # Any unknown doc_type should fall back to the 'unknown' schema
    # (SchemaRegistry.get returns the unknown schema when the key is missing).
    s = reg.get("this_doc_type_does_not_exist")
    assert s is not None
    assert s.doc_type == "unknown"
