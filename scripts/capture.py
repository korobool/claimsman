#!/usr/bin/env python3
"""Capture screenshots of the live Claimsman deployment.

Usage:
    python scripts/capture.py                        # defaults → docs/screenshots/latest/
    python scripts/capture.py --milestone M2
    CLAIMSMAN_BASE_URL=http://127.0.0.1:8811 python scripts/capture.py
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_BASE_URL = os.environ.get("CLAIMSMAN_BASE_URL", "http://108.181.157.13:8811")
REPO_ROOT = Path(__file__).resolve().parents[1]


SCREENS = [
    {"name": "01-inbox-empty", "path": "/app/", "wait_ms": 1200},
    {"name": "02-new-claim", "path": "/app/new", "wait_ms": 800},
    {"name": "03-audit", "path": "/app/audit", "wait_ms": 400},
    {"name": "04-settings", "path": "/app/settings", "wait_ms": 400},
]


def run(base_url: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[capture] base_url={base_url}")
    print(f"[capture] out_dir={out_dir}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            color_scheme="dark",
        )
        page = ctx.new_page()
        for shot in SCREENS:
            url = base_url.rstrip("/") + shot["path"]
            print(f"[capture] → {shot['name']}  {url}")
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(shot["wait_ms"])
            target = out_dir / f"{shot['name']}.png"
            page.screenshot(path=str(target), full_page=True)
            print(f"[capture]   saved {target}")
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--milestone", default="latest")
    args = parser.parse_args()
    out_dir = REPO_ROOT / "docs" / "screenshots" / args.milestone
    run(args.base_url, out_dir)


if __name__ == "__main__":
    main()
