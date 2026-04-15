# Claimsman runbook

This runbook covers day-to-day operation of a Claimsman deployment. It
assumes a single-server setup — which is the only topology Claimsman
supports today (one Python process, one port, one Postgres, one host
Ollama).

## Topology

```
reviewer browser
       │ HTTPS
       ▼
┌────────────────────────┐       ┌────────────────────┐
│ Claimsman web process  │       │ Ollama (host-local) │
│ apps.web.main          │──────▶│ Gemma 4 vision      │
│ uvicorn on port 8811   │       └────────────────────┘
│ in-process pipeline    │
│  (ingest / OCR /       │
│   classify / extract / │       ┌────────────────────┐
│   analyze / decide)    │──────▶│ Postgres 16 (Docker)│
└────────────────────────┘       │ port 55432          │
                                 └────────────────────┘
```

- One Python process (`python -m apps.web.main`) runs in a persistent
  `tmux` session called `claimsman` on the dev server.
- Postgres runs in Docker via `deploy/docker-compose.yml` on a
  non-default port (55432).
- Ollama is **host-installed** (not in Docker). Claimsman consumes it
  via `http://127.0.0.1:11434`.
- Surya OCR + SigLIP 2 run in the same Python process and load their
  weights lazily on first use. Models cache under
  `~/.cache/huggingface/`.

## Environment

| Var | Default | Notes |
| --- | --- | --- |
| `CLAIMSMAN_PORT` | `8811` | Bind port |
| `CLAIMSMAN_HOST` | `0.0.0.0` | Bind host |
| `CLAIMSMAN_LOG_LEVEL` | `info` | Maps to structlog + uvicorn |
| `CLAIMSMAN_POSTGRES_*` | see `deploy/.env.example` | DB connection |
| `CLAIMSMAN_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama |
| `CLAIMSMAN_OLLAMA_DEFAULT_MODEL` | `gemma4:31b` | Extract + decide default |
| `CLAIMSMAN_SURYA_DEVICE` | `cpu` | Surya torch device (`cpu` or `cuda`) |
| `CLAIMSMAN_SIGLIP_DEVICE` | `cpu` | SigLIP torch device |
| `CLAIMSMAN_CONFIG_ROOT` | `<repo>/config` | Where schemas/domains are loaded from |

## Deploy

From the repo root on the dev server:

```bash
bash scripts/deploy.sh
```

That script:

1. `git pull --ff-only`
2. Ensures Postgres is running via `docker compose -f deploy/docker-compose.yml up -d`
3. Creates/updates the Python venv (with `get-pip.py` fallback when `ensurepip` is missing)
4. Installs PyTorch (CPU wheel) + `requirements.txt`
5. Runs `alembic upgrade head`
6. Runs `npm ci && npm run build` inside `apps/frontend/` — the built bundle lands in `apps/web/static/app/`
7. Kills and restarts the `claimsman` tmux session running `python -m apps.web.main`

The last line of the log will read `[deploy] backend up on :8811` on success.

## Observing the live process

- Attach to the live log: `bash scripts/logs.sh` (or `tmux a -t claimsman`)
- Tail the log file: `tail -f /tmp/claimsman.log`
- Health check: `curl -fsS http://localhost:8811/healthz`
- Full API status: `GET /api/v1/system/info`
- Dashboard in the browser: **`/app/dev`** (live, 3s refresh)
- Per-area admin panels: **`/app/settings/health`**, **`/app/settings/llm`**

## Visual verification

All visual verification uses the **Claude-in-Chrome** extension connected to the
deployed instance at `http://108.181.157.13:8811/app/`. Screenshots are NOT
committed to the repo (see `.gitignore` and `memory/feedback_no_generated_artifacts_in_repo.md`).

For local automation (CI smoke tests), `scripts/capture.py` uses Playwright
to screenshot the primary screens against `CLAIMSMAN_BASE_URL`. Outputs
go under `docs/screenshots/<milestone>/` which is gitignored.

## Common tasks

### Add a new document type (schema)

1. Open **Settings → Schemas**, click **Generate from sample**.
2. Upload a representative scan/PDF of the new document type.
3. Claimsman runs ingest + Surya OCR, then asks Gemma 4 to propose a
   schema in YAML. The editor is pre-filled with the proposal.
4. Adjust fields/types/domains if needed, then click **Save**.
5. The new schema is written to `config/schemas/<doc_type>.yaml` and
   hot-reloaded into the running process.

### Add a new domain

1. **Settings → Domains → Generate with LLM**.
2. Describe the domain in plain language (e.g., *"Travel insurance
   claims for trip cancellation, medical evacuation, and lost
   baggage..."*).
3. Review the generated YAML, edit if needed, **Save**.
4. Domain becomes selectable at claim intake.

To add custom rules for the new domain, drop a file at
`config/domain_rules/<code>.py` exporting a `RULES = [fn, fn, ...]`
list. Each function takes a `ClaimContext` and returns a list of
`RuleFinding`. See `config/domain_rules/health_insurance.py` for a
template.

### Reprocess a claim

- From the Claim Detail header, **Re-run** re-runs the whole pipeline.
- **Add documents** appends files to an existing claim and re-runs.
  The pipeline is idempotent across stages: previously-processed
  pages are kept; new pages get ingest → OCR → classify → extract;
  analyze and decide regenerate across the full evidence set.

### Reviewer actions

On a `ready_for_review` claim, the right-rail **Proposed decision**
card shows the Gemma 4 proposal (outcome + amount + rationale) and
exposes:

- **Approve** / **Partial approve** / **Deny** / **Needs info**
  buttons — single-click confirm with the proposed values.
- **Edit…** opens a form to override outcome/amount/rationale before
  confirming.
- Once confirmed, the claim state moves to `decided` (or `escalated`
  for `needs_info`) and the card shows who confirmed it and when.
- **Reopen** drops a confirmed claim back into `under_review` for
  further review.

All actions are audited in the `audit_log` table.

## Troubleshooting

### Pipeline stuck at `processing`

1. Check `scripts/logs.sh` for `pipeline.ocr.error`, `pipeline.extract.error`,
   or `pipeline.decide.error` structured events.
2. For OCR: Surya models download on first use (~1-2 GB). First run
   after a fresh deploy can take several minutes per page.
3. For LLM stages: check `Settings → Health` or `/api/v1/llm/status`.
   If Ollama is unreachable, verify the host service is running with
   `curl http://127.0.0.1:11434/api/tags` on the server.
4. Click **Re-run** in the Claim Detail header to restart the full
   pipeline. It is safe to do so repeatedly.

### Frontend shows "frontend_not_built"

Run the build step manually:

```bash
npm --prefix apps/frontend ci
npm --prefix apps/frontend run build
```

The output lives at `apps/web/static/app/index.html`, which FastAPI
mounts at `/app`.

### Polygons drift off the text in the page viewer

This was fixed in commit `f03b8f8`. The viewer's SVG overlay now uses
`preserveAspectRatio="none"` with the native page pixel space as
`viewBox` so polygons scale correctly as the image is resized. If you
see misalignment, hard-reload the page to clear a cached older JS
bundle.

### Classification picks wrong labels

SigLIP 2 zero-shot has known limitations on non-English scanned
documents. The spec's hard-gate logic in `_stage_decide` is the safety
net: an error-severity finding forces the proposed outcome away from
`approve`, so a classification slip rarely causes a *wrong* decision —
it causes a `needs_info` decision with a clear rationale, which a
reviewer can then correct from the right-rail action buttons.

## Security & privacy reminders

- Never commit sample documents containing PII. Test bundles belong in
  `/tmp` or outside the repo.
- `task/input.md` is gitignored — it contains the original project brief.
- Screenshots and model caches are gitignored; see
  `memory/feedback_no_generated_artifacts_in_repo.md`.
- The API is currently unauthenticated. Do not expose Claimsman to the
  public internet without the auth milestone that comes next.
