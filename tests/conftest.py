"""Shared pytest fixtures and path setup.

The repo is a flat layout: ``apps/web`` and ``packages/`` are both
importable from the repo root. We make sure the repo root is on
``sys.path`` so tests can do ``from apps.web.routers...`` and
``from packages.schemas...`` without an editable install.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
