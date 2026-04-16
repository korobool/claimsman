# Claimsman

_A single-tenant, AI-assisted claims management workstation._

Claimsman turns a bundle of raw claim documents — PDFs, scans, photos,
handwritten prescriptions — into a reviewed, auditable payout decision.
Every AI stage (OCR, classification, extraction, analysis, decisioning)
runs inside a single Python process against local GPU hardware, and the
human reviewer stays in charge of every decision.

## Pointers

| If you want to… | Read |
| --- | --- |
| Understand what Claimsman is and why it exists | [`docs/claimsman-overview.md`](docs/claimsman-overview.md) |
| See it in action | [`docs/visual-runs/claim-demo/`](docs/visual-runs/claim-demo/) and [`docs/visual-runs/handwriting-demo/`](docs/visual-runs/handwriting-demo/) (re-run locally; gitignored) |
| Build, run, deploy, operate | [`docs/runbook.md`](docs/runbook.md) |
| Extend the code — APIs, data model, pipeline internals | [`documentation.md`](documentation.md) |
| Implementation specification | [`task/SPEC.md`](task/SPEC.md) |

## At a glance

- **Single process, single port.** FastAPI + compiled React SPA served by
  one Uvicorn worker on `:8811`. No second Node process, no separate
  workers, no RPC layer.
- **Surya** for OCR, **SigLIP 2** for zero-shot classification,
  **Gemma 4** (via local **Ollama**) for extraction, analysis and
  decision rationale — all running locally on NVIDIA hardware.
- **Four-step reviewer workflow.** Intake → Recognition → Analysis →
  Review, each a first-class, navigable screen.
- **Human-in-the-loop tools** that reviewers actually use: Add BBox
  (enforced re-recognition), double-click text edit, per-document
  re-recognise.
- **Auditable.** Every reviewer action and every pipeline transition
  writes an `AuditLog` row. `/app/audit` shows the live feed.
- **Configurable.** Domains, schemas and rules are data and plain Python
  — not a vendor DSL.

## Quickstart (local dev)

```bash
git clone git@github.com:korobool/claimsman.git
cd claimsman

# 1. Python venv + deps (use scripts/deploy.sh on a real server;
#    this is the shortcut for local dev).
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 2. Postgres 16 (via Docker)
cp deploy/.env.example .env
docker compose --env-file .env -f deploy/docker-compose.yml up -d postgres

# 3. DB migrations
set -a; source .env; set +a
alembic upgrade head

# 4. Frontend bundle (compiled into apps/web/static/app)
npm --prefix apps/frontend ci
npm --prefix apps/frontend run build

# 5. Run the single process
python -m apps.web.main
```

Visit `http://127.0.0.1:8811/app/` — the Inbox should render.

For deployment to a GPU host, use `scripts/deploy.sh`, which auto-detects
CUDA, installs the right torch wheel, and brings the service up under
tmux. See [`docs/runbook.md`](docs/runbook.md).

## Repository layout

```
apps/
  web/              FastAPI backend + compiled SPA served at /app
    routers/        HTTP routes (claims, audit, dev, settings, …)
    main.py         App factory + SPAStaticFiles (SPA deep-link fallback)
  frontend/         React 18 + Vite source; builds into apps/web/static/app
packages/
  ingest/           PDF/image/DOCX ingest, page rasterisation
  ocr/              Surya wrapper (FoundationPredictor + Rec + Det)
  classify/         SigLIP 2 zero-shot classification
  extract/          Gemma 4 schema-driven extraction
  analyze/          Cross-document rule engine
  decide/           Proposed-decision generator
  pipeline/         Orchestrator that walks every claim through all stages
  db/               SQLAlchemy models + async session
config/
  domains/          YAML domain packs (health_insurance, motor_insurance)
  schemas/          YAML document schemas
  domain_rules/     Pure-Python rule modules per domain
deploy/
  docker-compose.yml   Postgres 16 on port 55432
  .env.example         Environment template
scripts/
  deploy.sh         GPU-aware one-shot deploy for the dev server
  logs.sh           tmux attach shortcut
tests/
  test_*.py         Unit + integration tests (pytest)
  e2e_browser.py    Playwright E2E smoke suite
  demo_bg_bundle.py Full 23-beat narrated demo recording
  demo_handwriting.py  Handwriting-recovery demo recording
docs/
  claimsman-overview.md   Shareable product overview
  runbook.md              Deploy + operate
  visual-runs/            Generated demo output (gitignored)
task/
  SPEC.md           Implementation specification
documentation.md    Technical reference (this repo)
```

## Tests

```bash
# Unit + integration (fast)
.venv/bin/python -m pytest tests/ -x

# API smoke tests (hits a running server via CLAIMSMAN_TEST_BASE_URL)
.venv/bin/python -m pytest tests/test_api_smoke.py

# Playwright E2E (visits every primary screen on the deployed instance)
CLAIMSMAN_TEST_BASE_URL=http://108.181.157.13:8811 \
  .venv/bin/python tests/e2e_browser.py

# Narrated demo (opens a visible Chrome window; video + screenshots)
CLAIMSMAN_DEMO_HEADLESS=0 .venv/bin/python tests/demo_bg_bundle.py
CLAIMSMAN_DEMO_HEADLESS=0 .venv/bin/python tests/demo_handwriting.py
```

## Contributing

This project is single-tenant and pre-auth. Before opening a PR:

1. Run the unit test suite (`pytest tests/`).
2. Run the Playwright E2E smoke suite against a live deployment.
3. Do not commit generated artifacts — screenshots, build outputs, model
   caches, demo recordings and logs are all gitignored by design.
4. Commit messages should focus on the _why_, not the _what_.

## License

All rights reserved. Single-tenant internal tool; not for public
redistribution.
