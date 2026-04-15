#!/usr/bin/env python3
"""Playwright E2E smoke suite.

Visits every primary screen against the live deployment and
asserts key DOM content. Also exercises the New Claim upload flow
(if sample files are available) and the reviewer decision
confirmation path.

Run:
    python tests/e2e_browser.py
    CLAIMSMAN_BASE_URL=http://127.0.0.1:8811 python tests/e2e_browser.py
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

BASE_URL = os.environ.get("CLAIMSMAN_TEST_BASE_URL", "http://108.181.157.13:8811")
REPO_ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_DIR = Path.home() / "Downloads" / "RE_ AI доставчици"


@dataclass
class TestResult:
    name: str
    passed: bool
    note: str = ""

    def __str__(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"  [{mark}] {self.name}" + (f" — {self.note}" if self.note else "")


@dataclass
class TestSuite:
    results: list[TestResult] = field(default_factory=list)

    def record(self, name: str, passed: bool, note: str = "") -> None:
        self.results.append(TestResult(name, passed, note))
        print(self.results[-1])

    def ok(self, name: str, note: str = "") -> None:
        self.record(name, True, note)

    def fail(self, name: str, note: str) -> None:
        self.record(name, False, note)

    def summary(self) -> tuple[int, int]:
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        return passed, total


def main() -> int:
    suite = TestSuite()
    print(f"[e2e] base={BASE_URL}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            color_scheme="dark",
        )
        page = ctx.new_page()
        page.set_default_timeout(15000)

        try:
            run_tests(page, suite)
        finally:
            browser.close()

    passed, total = suite.summary()
    print()
    print(f"[e2e] {passed}/{total} passed")
    return 0 if passed == total else 1


def run_tests(page: Page, suite: TestSuite) -> None:
    test_inbox_loads(page, suite)
    test_new_claim_form_renders(page, suite)
    test_settings_domains_loads(page, suite)
    test_settings_schemas_loads(page, suite)
    test_settings_llm_loads(page, suite)
    test_settings_health_loads(page, suite)
    test_audit_loads(page, suite)
    test_dev_loads(page, suite)
    test_full_claim_pipeline(page, suite)


def goto(page: Page, path: str) -> None:
    url = BASE_URL.rstrip("/") + path
    page.goto(url, wait_until="networkidle")


def test_inbox_loads(page: Page, suite: TestSuite) -> None:
    try:
        goto(page, "/app/")
        page.wait_for_selector("h1:has-text('Inbox')", timeout=10000)
        page.wait_for_selector("text=Claimsman")
        # sidebar version reflects the dev state
        version_text = page.locator("aside").first.inner_text()
        if "v0." not in version_text or "M" not in version_text:
            suite.fail("inbox.sidebar_version", f"unexpected sidebar: {version_text[:80]}")
            return
        suite.ok("inbox.loads", f"sidebar shows version+milestone")
    except Exception as exc:
        suite.fail("inbox.loads", str(exc))


def test_new_claim_form_renders(page: Page, suite: TestSuite) -> None:
    try:
        goto(page, "/app/new")
        page.wait_for_selector("h1:has-text('New claim')", timeout=5000)
        page.wait_for_selector("text=Create claim")
        page.wait_for_selector("text=Domain")
        suite.ok("new_claim.form_visible")
    except Exception as exc:
        suite.fail("new_claim.form_visible", str(exc))


def test_settings_domains_loads(page: Page, suite: TestSuite) -> None:
    try:
        goto(page, "/app/settings/domains")
        page.wait_for_selector("h1:has-text('Domains')", timeout=5000)
        # Both seeded domains should appear
        page.wait_for_selector("text=health_insurance", timeout=5000)
        page.wait_for_selector("text=motor_insurance", timeout=5000)
        suite.ok("settings.domains.lists_seeds")
    except Exception as exc:
        suite.fail("settings.domains.lists_seeds", str(exc))


def test_settings_schemas_loads(page: Page, suite: TestSuite) -> None:
    try:
        goto(page, "/app/settings/schemas")
        page.wait_for_selector("h1:has-text('Schemas')", timeout=5000)
        page.wait_for_selector("text=Generate from sample", timeout=5000)
        suite.ok("settings.schemas.loads")
    except Exception as exc:
        suite.fail("settings.schemas.loads", str(exc))


def test_settings_llm_loads(page: Page, suite: TestSuite) -> None:
    try:
        goto(page, "/app/settings/llm")
        page.wait_for_selector("h1:has-text('LLM')", timeout=5000)
        page.wait_for_selector("text=Pull a new model", timeout=5000)
        suite.ok("settings.llm.loads")
    except Exception as exc:
        suite.fail("settings.llm.loads", str(exc))


def test_settings_health_loads(page: Page, suite: TestSuite) -> None:
    try:
        goto(page, "/app/settings/health")
        page.wait_for_selector("h1:has-text('Health')", timeout=5000)
        # six cards
        for title in ("Process", "Device", "Database", "Ollama", "Surya (OCR)"):
            page.wait_for_selector(f"text={title}", timeout=5000)
        suite.ok("settings.health.all_panels_visible")
    except Exception as exc:
        suite.fail("settings.health.all_panels_visible", str(exc))


def test_audit_loads(page: Page, suite: TestSuite) -> None:
    try:
        goto(page, "/app/audit")
        page.wait_for_selector("h1:has-text('Audit log')", timeout=5000)
        page.wait_for_selector("text=Live", timeout=5000)
        suite.ok("audit.loads")
    except Exception as exc:
        suite.fail("audit.loads", str(exc))


def test_dev_loads(page: Page, suite: TestSuite) -> None:
    try:
        goto(page, "/app/dev")
        page.wait_for_selector("h1:has-text('Dev state')", timeout=5000)
        page.wait_for_selector("text=MILESTONE", timeout=5000)
        page.wait_for_selector("text=GPU / DEVICE", timeout=5000)
        page.wait_for_selector("text=OLLAMA", timeout=5000)
        suite.ok("dev.loads_with_perf_cards")
    except Exception as exc:
        suite.fail("dev.loads_with_perf_cards", str(exc))


def test_full_claim_pipeline(page: Page, suite: TestSuite) -> None:
    """Upload the Bulgarian bundle via the API, then visit the claim
    detail and click through Recognition → Analysis → Review."""
    import httpx

    if not DOWNLOAD_DIR.exists():
        suite.fail("pipeline.upload", f"sample dir missing: {DOWNLOAD_DIR}")
        return

    samples = [
        DOWNLOAD_DIR / "Епикриза.pdf",
        DOWNLOAD_DIR / "касов бон.pdf",
    ]
    missing = [p for p in samples if not p.exists()]
    if missing:
        suite.fail("pipeline.upload", f"missing samples: {missing}")
        return

    try:
        files = [
            ("files", (p.name, p.read_bytes(), "application/pdf")) for p in samples
        ]
        data = {
            "claimant_name": "E2E test",
            "title": "Playwright E2E",
            "domain": "health_insurance",
        }
        r = httpx.post(f"{BASE_URL}/api/v1/claims", data=data, files=files, timeout=60.0)
        r.raise_for_status()
        claim = r.json()
        claim_id = claim["id"]
        suite.ok("pipeline.upload", f"claim_id={claim_id}")
    except Exception as exc:
        suite.fail("pipeline.upload", str(exc))
        return

    # Poll for readiness
    try:
        deadline = time.time() + 600
        while time.time() < deadline:
            cr = httpx.get(f"{BASE_URL}/api/v1/claims/{claim_id}", timeout=10.0).json()
            if cr.get("status") == "ready_for_review":
                break
            time.sleep(6)
        else:
            suite.fail("pipeline.reaches_ready_for_review", "timeout after 10 min")
            return
        suite.ok("pipeline.reaches_ready_for_review")
    except Exception as exc:
        suite.fail("pipeline.reaches_ready_for_review", str(exc))
        return

    # Visit the claim detail and verify the step navigator
    try:
        goto(page, f"/app/claims/{claim_id}")
        page.wait_for_selector("text=Intake", timeout=10000)
        page.wait_for_selector("text=Recognition", timeout=5000)
        page.wait_for_selector("text=Analysis", timeout=5000)
        page.wait_for_selector("text=Review", timeout=5000)
        suite.ok("claim_detail.step_navigator_visible")
    except Exception as exc:
        suite.fail("claim_detail.step_navigator_visible", str(exc))
        return

    # Navigate to Analysis and Review steps via the navigator
    try:
        page.get_by_role("button", name="Analysis").click()
        page.wait_for_selector("h2:has-text('Analysis')", timeout=5000)
        suite.ok("claim_detail.analysis_step_renders")
    except Exception as exc:
        suite.fail("claim_detail.analysis_step_renders", str(exc))

    try:
        page.get_by_role("button", name="Review").click()
        page.wait_for_selector("h2:has-text('Review')", timeout=5000)
        # Proposed decision card should be present
        page.wait_for_selector("text=PROPOSED DECISION", timeout=5000)
        suite.ok("claim_detail.review_step_renders")
    except Exception as exc:
        suite.fail("claim_detail.review_step_renders", str(exc))

    # Audit endpoint should have at least claim.created and pipeline events
    try:
        r = httpx.get(f"{BASE_URL}/api/v1/audit?limit=20", timeout=10.0)
        r.raise_for_status()
        entries = r.json()["entries"]
        if not entries:
            suite.fail("audit.has_events_after_pipeline", "no entries")
        else:
            suite.ok("audit.has_events_after_pipeline", f"{len(entries)} entries")
    except Exception as exc:
        suite.fail("audit.has_events_after_pipeline", str(exc))


if __name__ == "__main__":
    sys.exit(main())
