# Claimsman — Technical Documentation

A reference for developers working on Claimsman. For the conceptual
overview, see [`docs/claimsman-overview.md`](docs/claimsman-overview.md).
For deploy and day-to-day operations, see [`docs/runbook.md`](docs/runbook.md).

---

## 1. Architecture

Claimsman is one FastAPI process that hosts everything:

```
          ┌────────────────────────────────────────────────────────┐
          │               Uvicorn (single worker)                  │
          │                                                        │
  browser │   /app/*   ──▶  SPAStaticFiles → apps/web/static/app  │
   ──────▶│   /api/v1/*──▶  FastAPI routers                        │
          │                     │                                  │
          │                     ▼                                  │
          │              apps/web/pipeline/runner                  │
          │              (in-process asyncio + ThreadPoolExecutor) │
          │                     │                                  │
          │       ┌─────────────┴──────────────┐                   │
          │       ▼                            ▼                   │
          │  packages/ingest             packages/ocr (Surya)      │
          │  packages/classify           packages/extract (Gemma 4)│
          │  packages/analyze            packages/decide           │
          │                                                        │
          │  SQLAlchemy async ──▶ asyncpg ──▶ Postgres 16 (Docker) │
          │                                                        │
          │  httpx async        ──▶ Ollama on 127.0.0.1:11434      │
          │  torch + CUDA       ──▶ NVIDIA GPU                     │
          └────────────────────────────────────────────────────────┘
```

- **No second process.** React is compiled into `apps/web/static/app/`
  and served by the backend via a `SPAStaticFiles` subclass that falls
  back to `index.html` on 404 (so SPA deep-links like `/app/claims/:id`
  work on a hard reload).
- **No external queue.** `POST /api/v1/claims` creates DB rows and
  schedules a coroutine on the same event loop via
  `apps/web/pipeline/runner.py`.
- **Blocking work stays off the loop.** Surya, SigLIP and Gemma 4 calls
  are dispatched to a `ThreadPoolExecutor` so HTTP stays responsive
  during long OCR passes.

---

## 2. Directory map

```
apps/
  web/
    main.py            FastAPI app factory, SPA mount, router wiring
    config.py          Env-driven settings (pydantic)
    db.py              SQLAlchemy async engine + session dependency
    logging_setup.py   structlog JSON logger
    alembic/           Migrations
    models/            SQLAlchemy ORM — one file per table
    pipeline/
      runner.py        Claim pipeline orchestrator
    routers/           HTTP routes (see §5 for the full list)
    services/
      storage.py       Content-addressable file storage on disk
    static/app/        Built React bundle (gitignored output)
  frontend/
    src/
      pages/           Route components (Inbox, ClaimDetail, NewClaim, Settings*, Audit, Dev)
      components/      Shared widgets
      lib/api.ts       Typed API client
    vite.config.ts     Bundles into ../web/static/app
packages/
  ingest/              PDF/image/DOCX → IngestedDocument
  ocr/                 Surya wrapper (OcrEngine)
  vision/              SigLIP 2 classifier (zero-shot)
  extract/             Gemma 4 extractor + schema-driven parsers
  schemas/             YAML schema loader + validator
config/
  domains/             *.yaml — one per domain pack
  schemas/             *.yaml — one per document type
  domain_rules/        *.py — pure-Python rules, export RULES = [fn, ...]
deploy/
  docker-compose.yml   Postgres 16 service on port 55432
  .env.example         Environment template
scripts/
  deploy.sh            GPU-aware one-shot deploy
  logs.sh              tmux attach
tests/
  test_*.py            pytest unit + integration
  test_api_smoke.py    End-to-end API tests (requires live server)
  e2e_browser.py       Playwright smoke suite
  demo_bg_bundle.py    23-beat recorded demo
  demo_handwriting.py  Handwriting-recovery recorded demo
```

---

## 3. Data model

All tables live under `apps/web/models/`. Primary keys are UUIDs;
foreign keys cascade where it makes sense (deleting a `claim` drops its
uploads, documents, pages, findings, extracted fields, and decisions).

| Table | File | Role |
| --- | --- | --- |
| `claims` | `claim.py` | One row per claim. Holds code (`CLM-XXXXXXXX`), domain, claimant name, policy number, title, notes, status, and timestamps. |
| `uploads` | `upload.py` | Raw uploaded files for a claim — content-addressable path, filename, size, MIME type, SHA-256. |
| `documents` | `document.py` | Logical documents within a claim (one upload can expand to several — e.g. a multi-page PDF with mixed doc types can be split). Carries `doc_type`, display name, and a pointer back to the upload. |
| `pages` | `page.py` | Rasterised pages per document. Holds the image path, dimensions, OCR text (flat), `bbox_json` (polygon-level lines + confidence), SigLIP classification, text-layer usage flag. |
| `extracted_fields` | `extracted_field.py` | Schema-driven fields extracted by Gemma 4. Each row links back to the document and keeps a pointer to the source OCR line where possible. |
| `findings` | `finding.py` | Rule-engine + LLM findings. Severity is one of `info`, `warning`, `error`. Findings gate decisioning. |
| `decisions` | `decision.py` | Proposed and confirmed decisions. Carries outcome, amount, currency, rationale markdown, LLM model name, confirmer identity, confirmed timestamp, `is_proposed` flag. |
| `audit_log` | `audit_log.py` | Tamper-evident action log. Every reviewer action and every pipeline transition writes a row with `actor`, `entity`, `entity_id`, `action`, `before_json`, `after_json`. |

### Claim status state machine

```
uploaded ──▶ processing ──▶ ready_for_review ──▶ decided
                │                     │               │
                │                     └──▶ escalated  │
                └──▶ error                            │
                                                      ▼
                                                   reopened
                                                   (returns to under_review)
```

Enums live in `apps/web/models/claim.py` as `ClaimStatus` and
`DecisionOutcome`.

### Page `bbox_json` shape

```json
{
  "width": 1186,
  "height": 1644,
  "languages": ["bg", "en"],
  "lines": [
    {
      "text": "Nivalin 5 mg",
      "bbox": [25.0, 715.0, 525.0, 800.0],
      "confidence": 0.86,
      "polygon": [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]
    }
  ]
}
```

`width` and `height` are in **native page pixels**, which is the same
coordinate space the SVG overlay uses via `viewBox="0 0 width height"`.
Everything downstream (Add BBox tool, line edit, polygon rendering)
stays in native pixels — no scale juggling.

---

## 4. Pipeline

Entry point: `apps/web/pipeline/runner.py`. Each claim walks through
five stages, in order. Every stage is idempotent: re-running it on an
already-processed claim is safe and refreshes the output.

| Stage | Package | Responsibility |
| --- | --- | --- |
| 1. Ingest | `packages/ingest` | Normalise every upload to one or more page images with dimensions. PDF via `pypdfium2` at `PDF_RENDER_SCALE = 2.0` (~144 DPI). DOCX via `python-docx`. Images pass through after orientation normalisation. |
| 2. Recognition | `packages/ocr` | Surya 0.17+ `FoundationPredictor` → `RecognitionPredictor` + `DetectionPredictor`. Stores lines into `page.bbox_json`. |
| 3. Classification | `packages/vision` | SigLIP 2 zero-shot — label set filtered to the claim's active domain pack. |
| 4. Extraction | `packages/extract` | Schema-driven Gemma 4 extraction. Prompt includes OCR lines + target schema YAML; response is validated before it reaches `extracted_fields`. |
| 5. Analysis + Decision | Python rules + Gemma 4 | Loads rules for the active domain, runs them against the full claim state, produces `findings`, then asks Gemma 4 for a cross-document rationale and outcome. A proposed `decisions` row is written. |

### Stage re-entry

The `POST /api/v1/claims/{id}/reprocess` endpoint accepts
`{"stage": "ocr" | "classify" | "extract" | "analyze" | "decide" | "all"}`
and re-runs from that stage forward. Everything downstream is regenerated;
everything upstream is left alone.

### Enforced bbox recognition (the reviewer path)

`POST /api/v1/claims/{id}/pages/{page_id}/bboxes/recognize`:

1. Load the page's existing `bbox_json['lines']`.
2. Drop any line whose bbox overlaps the new rectangle by >30% of the
   existing line's area (`_bbox_overlaps` helper in `claims.py`).
3. Build `full_bbox_set = kept_existing + [new_bbox]`, in reading order.
4. Call `OcrEngine.recognize_bboxes(image, full_bbox_set)`. Because
   `bboxes=[...]` is passed explicitly, Surya **skips the detection
   pass entirely** and only runs recognition — the reviewer's geometry
   is honoured verbatim.
5. Replace `page.bbox_json['lines']` with the freshly-recognised set.
6. Write an `audit_log` row with the before/after text for the affected
   region.

This is the mechanism the handwriting demo relies on.

---

## 5. REST API

All API routes are mounted under `/api/v1`. Full router list is wired
in `apps/web/main.py`. Types: every request/response is JSON (except
`POST /claims` which is `multipart/form-data`).

### System

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/healthz` | Liveness probe. Returns `{"ok": true}`. |
| `GET` | `/api/v1/system/info` | Build info + resolved settings (no secrets). |

### Claims

| Method | Path | Notes |
| --- | --- | --- |
| `GET`  | `/api/v1/claims` | List claims, newest first. Pagination params. |
| `POST` | `/api/v1/claims` | Create a claim. Multipart: `files[]`, `claimant_name`, `policy_number`, `title`, `domain`, `notes`. |
| `GET`  | `/api/v1/claims/{id}` | Full claim payload: uploads, documents, pages, findings, extracted fields, decisions, pipeline stage. |
| `POST` | `/api/v1/claims/{id}/uploads` | Append files to an existing claim. Triggers a partial reprocess. |
| `POST` | `/api/v1/claims/{id}/reprocess` | Re-run the pipeline from a given stage. Body: `{"stage": "ocr" \| "classify" \| "extract" \| "analyze" \| "decide" \| "all", "document_id": "<uuid>"}`. |
| `GET`  | `/api/v1/claims/{id}/pages/{page_id}/image` | Serve the raw rasterised page image. |
| `PATCH`| `/api/v1/claims/{id}/pages/{page_id}/ocr-line` | Edit a single OCR line's text. Body: `{"index": int, "text": str}`. Audited. |
| `POST` | `/api/v1/claims/{id}/pages/{page_id}/bboxes` | Append a user-authored line (text + polygon/bbox). Audited. |
| `POST` | `/api/v1/claims/{id}/pages/{page_id}/bboxes/recognize` | **Enforced bbox re-recognition.** Body: `{"bbox":[x0,y0,x1,y1], "polygon": [[x,y]...]}`. See §4. |
| `POST` | `/api/v1/claims/{id}/decision/confirm` | Confirm (or override) the proposed decision. Body: `{"outcome", "amount", "currency", "rationale_md", "reviewer"}`. |
| `POST` | `/api/v1/claims/{id}/decision/reopen` | Drop a confirmed claim back to `under_review`. |

### Audit

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/v1/audit` | Paginated audit log feed. Used by the live Audit screen. |

### Dev + health dashboard

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/v1/dev/state` | Live dev-dashboard payload: version, milestone, GPU stats, Ollama state, DB counts, Surya warmup. |
| `GET` | `/api/v1/health/panels` | Six-panel health check (Process, Device, Database, Ollama, Surya, SigLIP). |

### LLM / model management

| Method | Path | Notes |
| --- | --- | --- |
| `GET`  | `/api/v1/llm/status` | Ollama reachability + current default model. |
| `GET`  | `/api/v1/llm/models` | `ollama tags`-equivalent listing. |
| `POST` | `/api/v1/llm/pull` | Start a model-pull job. Returns `{job_id}`. |
| `GET`  | `/api/v1/llm/pull/{job_id}` | Poll a pull job for progress + status. |

### Domains

| Method | Path | Notes |
| --- | --- | --- |
| `GET`    | `/api/v1/domains` | List domain packs. |
| `GET`    | `/api/v1/domains/{code}` | Single domain's metadata + YAML. |
| `POST`   | `/api/v1/domains` | Create a domain pack. |
| `PUT`    | `/api/v1/domains/{code}` | Update metadata. |
| `PUT`    | `/api/v1/domains/{code}/yaml` | Replace the raw YAML body. |
| `POST`   | `/api/v1/domains/generate` | LLM-assisted domain scaffolder. Body: `{"description": str}`. Returns proposed YAML. |
| `DELETE` | `/api/v1/domains/{code}` | Delete a domain pack. |

### Schemas

| Method | Path | Notes |
| --- | --- | --- |
| `GET`  | `/api/v1/schemas` | List registered document schemas. |
| `GET`  | `/api/v1/schemas/{doc_type}` | One schema's YAML + metadata. |
| `PUT`  | `/api/v1/schemas/{doc_type}/yaml` | Replace the raw YAML body. |
| `POST` | `/api/v1/schemas/generate/from-file` | Generate a schema YAML from an uploaded sample document. |
| `POST` | `/api/v1/schemas/generate/from-text` | Generate a schema YAML from a natural-language description. |

---

## 6. Frontend

- React 18 + TypeScript + Vite + Tailwind CSS.
- Dark-theme first-class; the `color-scheme: dark` meta is hard-coded.
- Pages under `apps/frontend/src/pages/`:
  - `Inbox.tsx` — claim list, virtualised, with live status polling.
  - `NewClaim.tsx` — upload form with drag-drop + file-picker.
  - `ClaimDetail.tsx` — four-step reviewer workflow. Owns the native
    SVG overlay for polygons and the Add BBox tool. Uses native
    `addEventListener` for mouse events on the SVG because React's
    synthetic events did not reliably reach the element.
  - `Audit.tsx` — live audit feed.
  - `Dev.tsx` — dev dashboard.
  - `settings/Domains.tsx`, `settings/Schemas.tsx`, `settings/LLM.tsx`,
    `settings/Health.tsx`.
- API client: `apps/frontend/src/lib/api.ts` — one typed function per
  route. `createClaim` posts `FormData`; everything else is JSON.
- Build: `npm --prefix apps/frontend run build` drops the bundle into
  `apps/web/static/app/`, which `SPAStaticFiles` serves at `/app/*`.

---

## 7. Environment variables

See the full table in [`docs/runbook.md`](docs/runbook.md). The ones
that matter most day-to-day:

| Variable | Default | Effect |
| --- | --- | --- |
| `CLAIMSMAN_PORT` | `8811` | Uvicorn bind port. |
| `CLAIMSMAN_HOST` | `0.0.0.0` | Uvicorn bind host. |
| `CLAIMSMAN_SURYA_DEVICE` | `cpu` | `cuda` to put Surya on GPU. Auto-set by `deploy.sh` when `nvidia-smi` is present. |
| `CLAIMSMAN_SIGLIP_DEVICE` | `cpu` | Same, for SigLIP. |
| `CLAIMSMAN_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama. |
| `CLAIMSMAN_OLLAMA_DEFAULT_MODEL` | `gemma4:31b` | Default model for extract + decide. |
| `CLAIMSMAN_CONFIG_ROOT` | `<repo>/config` | Where domains/schemas/rules are loaded from. |
| `CLAIMSMAN_POSTGRES_*` | see `deploy/.env.example` | DB connection. |

---

## 8. Extending the system

### Add a new document type (schema)

Two routes: the UI route (**Settings → Schemas → Generate from
sample**) and the file-edit route.

**Via UI** (recommended): upload a representative sample; Claimsman
runs ingest + Surya + asks Gemma 4 for a YAML proposal; edit if needed;
save. The YAML lands at `config/schemas/<doc_type>.yaml`.

**By hand**: drop a YAML file in `config/schemas/`:

```yaml
doc_type: pharmacy_invoice
display_name: Pharmacy invoice
languages: [bg, en]
fields:
  - name: invoice_number
    type: string
    required: true
  - name: issue_date
    type: date
  - name: total_amount
    type: money
  - name: line_items
    type: list
    items:
      - { name: drug, type: string }
      - { name: quantity, type: number }
      - { name: unit_price, type: money }
      - { name: line_total, type: money }
```

Schemas are hot-reloaded on next claim ingest.

### Add a new domain pack

**Via UI**: **Settings → Domains → Generate with LLM**. Describe the
domain in plain language, review the proposed YAML, save.

**By hand**: drop a file at `config/domains/<code>.yaml`:

```yaml
code: travel_insurance
display_name: Travel insurance
vocabulary:
  - trip_cancellation
  - medical_evacuation
  - lost_baggage
required_documents:
  - booking_confirmation
  - medical_report
  - police_report
schemas:
  - booking_confirmation
  - medical_report
rules_module: config.domain_rules.travel_insurance
thresholds:
  auto_approve_confidence: 0.85
  max_auto_amount: 500.0
```

### Add rules for a domain

Drop a file at `config/domain_rules/<code>.py`:

```python
from packages.analyze import Finding, Severity

def check_trip_dates_consistent(claim):
    # claim is the full loaded claim context: claim, documents, pages, fields
    booking = claim.doc("booking_confirmation")
    medical = claim.doc("medical_report")
    if not booking or not medical:
        return []
    if medical.field("visit_date") > booking.field("return_date"):
        return [Finding(
            severity=Severity.ERROR,
            code="trip.medical_after_return",
            message="Medical visit recorded after the return flight.",
            doc_id=medical.id,
        )]
    return []

RULES = [check_trip_dates_consistent]
```

Any `Severity.ERROR` finding blocks auto-`approve` outcomes; the
proposed decision flips to `needs_info` with the finding cited in the
rationale.

---

## 9. Tests

| Suite | Command | What it covers |
| --- | --- | --- |
| Unit + integration | `.venv/bin/python -m pytest tests/ -x` | Domain rules (common, health, motor), schemas registry, ingest, extract parsers, claims router helpers. |
| API smoke | `.venv/bin/python -m pytest tests/test_api_smoke.py` | End-to-end against a live server. |
| Playwright E2E | `python tests/e2e_browser.py` | Visits every primary screen, drives the full claim pipeline against the 6-doc bundle, asserts key DOM content. |
| Demo recorder (full flow) | `CLAIMSMAN_DEMO_HEADLESS=0 python tests/demo_bg_bundle.py` | 23-beat narrated reviewer walk-through with video + screenshots. |
| Demo recorder (handwriting) | `CLAIMSMAN_DEMO_HEADLESS=0 python tests/demo_handwriting.py` | Handwriting recovery via enforced bbox. |

Set `CLAIMSMAN_TEST_BASE_URL` / `CLAIMSMAN_DEMO_BASE_URL` to point a
suite at a specific deployment (default: `http://108.181.157.13:8811`).

---

## 10. Known constraints

- **Single-tenant, unauthenticated.** There is no login, no session, no
  RBAC. Do not expose Claimsman to the public internet.
- **Single-worker Uvicorn.** Required — the pipeline keeps mutable
  in-memory state (Surya warm model, SigLIP warm model, Ollama session
  pool). Multi-worker deployment would need a serious rework.
- **Surya is the only OCR.** There is no fallback. If Surya fails on a
  document, the reviewer recovers via Add BBox or line edit — not via a
  secondary engine.
- **transformers must be `<5`.** Surya 0.17 does not run against
  `transformers 5.x` (see `pipeline` wrapper changes) — the pin is in
  `requirements.txt`.

For the full constraint list and the "why," see
[`task/SPEC.md`](task/SPEC.md).
