"""Smoke tests that hit the live deployed backend via HTTP.

These run against ``CLAIMSMAN_BASE_URL`` (defaults to the dev-server
deployment) and verify every public endpoint returns a sane shape.
They are skipped gracefully if the base URL isn't reachable so the
same suite still runs in environments without the dev server.
"""
from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("CLAIMSMAN_TEST_BASE_URL", "http://108.181.157.13:8811")
TIMEOUT = 10.0


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    try:
        c = httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)
        c.get("/healthz").raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"live backend at {BASE_URL} not reachable: {exc}")
    yield c
    c.close()


def test_root_healthz(client: httpx.Client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_system_healthz(client: httpx.Client) -> None:
    r = client.get("/api/v1/system/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_system_info_has_ollama(client: httpx.Client) -> None:
    r = client.get("/api/v1/system/info")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "claimsman"
    assert "ollama" in data
    assert "default_model" in data["ollama"]


def test_schemas_endpoint(client: httpx.Client) -> None:
    r = client.get("/api/v1/schemas")
    assert r.status_code == 200
    schemas = r.json()["schemas"]
    doc_types = {s["doc_type"] for s in schemas}
    assert "prescription" in doc_types
    assert "receipt" in doc_types
    assert "unknown" in doc_types
    assert len(schemas) >= 14


def test_domains_endpoint(client: httpx.Client) -> None:
    r = client.get("/api/v1/domains")
    assert r.status_code == 200
    codes = {d["code"] for d in r.json()["domains"]}
    assert "health_insurance" in codes
    assert "motor_insurance" in codes


def test_audit_endpoint_shape(client: httpx.Client) -> None:
    r = client.get("/api/v1/audit?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    assert isinstance(data["entries"], list)


def test_claims_list_endpoint(client: httpx.Client) -> None:
    r = client.get("/api/v1/claims")
    assert r.status_code == 200
    data = r.json()
    assert "claims" in data
    assert isinstance(data["claims"], list)


def test_llm_status_endpoint(client: httpx.Client) -> None:
    r = client.get("/api/v1/llm/status")
    assert r.status_code == 200
    data = r.json()
    assert "reachable" in data
    assert "default_model" in data


def test_llm_models_endpoint(client: httpx.Client) -> None:
    r = client.get("/api/v1/llm/models")
    # On a fresh server this can 502 if Ollama is down; allow that.
    if r.status_code == 502:
        pytest.skip("ollama unreachable from the server")
    assert r.status_code == 200
    data = r.json()
    assert "models" in data
    assert "default_model" in data


def test_health_panels_endpoint(client: httpx.Client) -> None:
    r = client.get("/api/v1/health/panels")
    assert r.status_code == 200
    data = r.json()
    for key in ("process", "device", "database", "ollama", "surya", "siglip"):
        assert key in data, f"missing panel: {key}"


def test_dev_state_endpoint_returns_perf(client: httpx.Client) -> None:
    r = client.get("/api/v1/dev/state")
    assert r.status_code == 200
    data = r.json()
    assert "app" in data
    assert "milestone" in data
    assert "db" in data
    assert "perf" in data
    perf = data["perf"]
    assert "cuda_available" in perf
    assert "surya_loaded" in perf
    assert "siglip_loaded" in perf


def test_openapi_has_expected_routes(client: httpx.Client) -> None:
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    paths = set(spec["paths"].keys())
    expected = {
        "/api/v1/system/healthz",
        "/api/v1/claims",
        "/api/v1/claims/{claim_id}",
        "/api/v1/claims/{claim_id}/decision/confirm",
        "/api/v1/claims/{claim_id}/pages/{page_id}/bboxes/recognize",
        "/api/v1/domains",
        "/api/v1/domains/generate",
        "/api/v1/schemas",
        "/api/v1/schemas/generate/from-file",
        "/api/v1/llm/status",
        "/api/v1/llm/models",
        "/api/v1/llm/pull",
        "/api/v1/audit",
        "/api/v1/dev/state",
        "/api/v1/health/panels",
    }
    missing = expected - paths
    assert not missing, f"OpenAPI spec is missing routes: {missing}"
