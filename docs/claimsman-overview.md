# Claimsman — Product Overview

_A single-tenant, AI-assisted claims management workstation for insurance reviewers._

Claimsman turns a pile of raw claim documents — scans, photos, PDFs, screenshots
of chat messages — into a reviewed, auditable payout decision. It runs every AI
stage (OCR, classification, extraction, analysis, decisioning) inside a single
Python process against local GPU hardware, and it keeps the human reviewer in
charge of every decision.

---

## 1. The problem

A claims reviewer's day is dominated by low-value work:

- Reading the same Bulgarian, English and Cyrillic documents again and again.
- Transcribing amounts, diagnosis codes and drug names into spreadsheets.
- Double-checking totals that could be added up automatically.
- Hunting for the one paragraph that contradicts the claimant's story.
- Writing a short rationale paragraph for every decision, in a style that
  survives audit.

None of this is judgment work. It's search, arithmetic and formatting. The
judgment — "does this claim get paid, and for how much" — is hidden under
hours of that drudgery.

The obvious answer, "run the docs through an OCR API and ask an LLM," is
wrong for three reasons:

1. **Insurance data is private.** You cannot ship scanned passports or medical
   records to a third-party API without a hard conversation with your legal
   team.
2. **Black-box decisions don't survive audit.** Regulators want to see _which
   line of which document_ drove a payout.
3. **Reviewers don't want a ghost in the seat.** They want a tireless
   assistant that does the reading, proposes an answer, shows its work, and
   steps aside when a human needs to take over.

Claimsman is built around those three constraints.

---

## 2. What Claimsman is

Claimsman is a web application that:

- Accepts any bundle of documents for a single claim (PDFs, images, DOCX,
  scanned receipts, handwritten prescriptions).
- Runs all recognition and reasoning **locally**, against models that live on
  the reviewer's own GPU.
- Presents the claim as a four-step reviewer workflow: **Intake → Recognition
  → Analysis → Review**, where every step is a real, navigable screen and not
  a loading spinner.
- Produces a proposed decision (approve / partial-approve / deny / needs
  info) with a written rationale that cites the specific lines that support
  it.
- Never commits a decision without an explicit reviewer confirmation. The
  reviewer can always override.
- Records every action — automated or human — in a tamper-evident audit log.

You can think of it as the opposite of a black-box "AI claims adjuster." It's
a tool that makes the reviewer dramatically faster without taking the pen out
of their hand.

---

## 3. How it works — the pipeline

Every claim goes through five pipeline stages. All of them run inside the
same Python process as the web server, which means there are no queues, no
handoffs, and no second instances to keep alive.

### 3.1 Ingest

- Every upload is written to disk under `~/.claimsman/uploads/<claim>/` with
  a content-addressable name (SHA-256 of the file bytes). Duplicates collapse
  naturally — the same invoice uploaded twice never takes up twice the
  storage.
- MIME type is verified with `python-magic`, not trusted from the browser.
- PDFs are rasterised to per-page images via `pypdfium2`; DOCX is expanded via
  `python-docx`; images pass straight through after normalisation.
- A structured `IngestedDocument` is handed to the OCR stage.

### 3.2 Recognition (OCR) — Surya

- **Surya** is Claimsman's only OCR engine. There is no fallback, no remote
  endpoint, and no "traditional" engine sitting behind it. That's a
  deliberate simplification — one model, one set of polygons, one confidence
  number per line.
- Surya runs on the local GPU (NVIDIA A40 on the dev server, ~45 GB VRAM),
  which brings per-page time from "tens of seconds on CPU" to "one or two
  seconds on GPU."
- Output is a list of `(polygon, text, confidence)` rows per page. Polygons
  are stored in native page-pixel coordinates so the frontend can draw them
  over the raster at any zoom level.
- **Critical feature — enforced recognition.** Claimsman exposes Surya's
  `recognize_bboxes` API directly to reviewers. When a reviewer draws a
  rectangle, the backend builds a fresh bbox set (keeping existing
  non-overlapping lines, adding the new rectangle) and runs Surya's
  recognition pass **with the detection pass skipped entirely**. The
  reviewer's geometry is treated as ground truth. See §5.

### 3.3 Classification — SigLIP 2

- Every recognised page is passed through **SigLIP 2**, a zero-shot
  image–text model, to decide what kind of document it is (invoice,
  prescription, discharge summary, receipt, outpatient report, …).
- The label set is filtered to the claim's active domain pack — a pharmacy
  receipt in a motor-insurance claim gets classified against motor labels,
  not against health labels. That keeps SigLIP from confidently mis-routing
  a document into the wrong schema.

### 3.4 Extraction — Ollama Gemma 4

- For every document type there is a YAML schema (e.g. `pharmacy_invoice`,
  `outpatient_report`, `prescription`). The schema declares the fields the
  downstream rules need: drug names, dosages, line totals, patient name,
  diagnosis codes, and so on.
- Extraction is done by **Gemma 4** running locally via **Ollama**. The
  prompt includes the document's OCR lines and the target schema; the
  response is validated against the schema before being stored.
- Every extracted field keeps a pointer to the OCR line it came from, so the
  review UI can highlight "this is where I got the number from."

### 3.5 Analysis + decisioning — Gemma 4 + Python rules

- Domain packs (`health_insurance`, `motor_insurance`, …) ship with a set of
  Python rules: "patient name must be consistent across all documents",
  "the sum of line items on the receipt must match the claimed total", "every
  drug must appear on the corresponding prescription," and so on. Rules are
  authored as plain Python functions so domain experts can audit them line
  by line.
- Gemma 4 is asked to produce a final cross-document rationale that cites
  the specific documents and line numbers.
- The output is a proposed decision with amount, currency, outcome and a
  Markdown rationale. The decision is proposed, not applied.

---

## 4. The reviewer experience

The reviewer works through four steps, and every step has its own screen.
Steps are navigable as a history — a reviewer can always go back to an
earlier step without losing context, so a deny-then-reconsider flow is one
click away.

### Step 1 — Intake

The uploaded files, file sizes, MIME types, per-file classification hints
and any ingest-time flags. This is the "did we get what we expected" step.

### Step 2 — Recognition

- Every document is shown on the left rail with its own status (OCR done,
  classification done, extraction done).
- The active page is displayed with polygon overlays coloured by
  confidence — high confidence is green, borderline is amber, low is red.
- The reviewer can pick any polygon to see what Surya read, in context.
- Reviewer tools live here: **Add BBox**, **Edit text**, **Re-recognise
  document**.

### Step 3 — Analysis

- Shows the extracted fields for every document, grouped by doc type, with
  a pointer back to the source line.
- Shows the cross-document findings with severity (info / warning / error)
  and a short explanation from the analysis stage.
- While Gemma 4 is still thinking, there's a "thinking" indicator on the
  step — no silent wait, ever.

### Step 4 — Review

- A compact summary card: claimant, policy, domain, findings counts.
- A proposed decision card: outcome, amount, currency, rationale.
- Four action buttons: **Approve**, **Partial approve**, **Deny**, **Needs
  info**. Every action requires an explicit reviewer confirmation and
  writes an audit row.

---

## 5. Reviewer tools — the human-in-the-loop parts

Claimsman is deliberately a workstation, not a replacement. Three tools on
the Recognition step give the reviewer direct control over what Surya and
Gemma 4 see:

### Add BBox (enforced re-recognition)

The headline reviewer tool. The reviewer:

1. Selects the **Add BBox** tool.
2. Drags a rectangle over the region they know contains text — typically a
   line that Surya either missed entirely or read as nonsense.
3. On mouseup, the frontend POSTs the rectangle to
   `/claims/{id}/pages/{page_id}/bboxes/recognize`.
4. The backend builds a **fresh bbox set** consisting of every existing
   line that does _not_ overlap the new rectangle by more than 30%, plus
   the new rectangle, and hands that set directly to
   `OcrEngine.recognize_bboxes(image, [...])`.
5. Surya's detection pass is **skipped entirely** — because `recognize_bboxes`
   is called with an explicit `bboxes=[...]` argument, Surya treats the
   geometry as ground truth and only runs the recognition model.
6. The returned lines replace the page's `bbox_json['lines']` list.

This is the single most important piece of human-in-the-loop engineering in
the system. The reviewer isn't fighting the OCR engine; they're feeding it
a hint the engine will respect. It turns "I can see that's a drug name but
Surya couldn't" from a five-minute detour into a one-second rectangle.

The **handwriting demo** under `docs/visual-runs/handwriting-demo/` shows
this end-to-end on a Bulgarian prescription:

- **Before** (Surya unaided): `'Nivali<br>2×1'` — drug name cut off, tag
  noise.
- **After** (enforced bbox): `'B) Nivalin 5'` — correct drug name, correct
  prefix, correct dose.

### Double-click to edit

Sometimes a line's geometry is fine but a single character is wrong. Any
polygon on the Recognition step is double-clickable, which opens a compact
inline editor. The reviewer types the corrected text and saves. The edit is
a normal audited event — the previous text is kept in the audit log.

### Re-recognise document

A per-document button that reruns OCR from scratch on a single document
(useful after swapping the file, or after tuning a page-level setting).
Only that document's OCR is rerun; the rest of the claim is left alone.

---

## 6. Domains, schemas and the settings surface

Not every insurance business looks like health insurance. Claimsman is
explicit about this: the domain and schema layer is data, not code.

### Domains

A domain bundles a vocabulary, a list of required documents, a set of
rule modules, and the active schemas. Claimsman ships with two seeded
domains — **health insurance** and **motor insurance** — but an admin can
create any number from the **Settings → Domains** screen. The domain
editor includes an LLM-assisted scaffolder: you write a natural-language
description of the domain, and Gemma 4 proposes the YAML to start from.

### Schemas

A schema is a YAML definition of what fields to extract from a particular
document type. Schemas are first-class, versioned, and can be generated
from a sample document: drop a sample invoice into **Settings → Schemas →
Generate from sample**, and Gemma 4 proposes the YAML based on what it
sees.

### Rules

Rules are plain Python functions in `config/domain_rules/`. Each rule
takes the full claim state and returns zero or more `Finding` objects
with a severity and a human-readable explanation. Rules are where domain
experts encode business-specific logic that shouldn't live inside an LLM
prompt.

### Other settings screens

- **Settings → LLM** — model manager for Ollama. Pull a new model with a
  live progress bar.
- **Settings → Health** — six reachability panels (Process, Device,
  Database, Ollama, Surya, SigLIP) so an admin can tell at a glance which
  subsystem is unhappy.

---

## 7. Architecture at a glance

- **One Python process.** The FastAPI backend and the compiled React SPA
  are served by the _same_ Uvicorn worker on `:8811`. There is no second
  Node process, no separate worker pool, no RPC layer.
- **In-process pipeline.** Claim uploads are enqueued to an asyncio task
  that walks the five pipeline stages in order. Long-running work (Surya
  OCR, SigLIP, Gemma 4 streaming) is offloaded to a `ThreadPoolExecutor`
  so the event loop stays responsive.
- **GPU where it matters.** Surya and SigLIP are moved to CUDA automatically
  at deploy time — `scripts/deploy.sh` auto-detects `nvidia-smi`, picks
  the right torch wheel (`cu128` by default), and patches `.env` so both
  engines pick up the device on next start.
- **Postgres 16** for every persistent row. Migrations are managed by
  Alembic. Postgres lives in Docker on a non-default port (`55432`) to
  keep it off the reviewer's day-to-day `psql`.
- **structlog JSON logging** everywhere, piped into a tmux session the
  admin can follow with `tmux attach -t claimsman`.
- **No commits of generated artifacts.** Screenshots, build outputs, demo
  recordings, logs and caches are gitignored. The repo is the source of
  truth for code and seed data, nothing else.

---

## 8. Audit and trust

Every reviewer action and every pipeline transition writes an `AuditLog`
row. Rows carry: actor, timestamp, entity type, entity id, action name,
a `before_json` snapshot and an `after_json` snapshot. Specifically:

- **Claim created** → includes the uploaded file list and domain choice.
- **OCR done / classification done / extraction done** → pipeline
  transitions.
- **Enforced bbox recognition** → records the page, the bbox coordinates,
  the replaced lines and the new lines.
- **OCR line edited** → records the line index, previous text, new text.
- **Decision proposed** → records the LLM model, the amount, the rationale.
- **Decision confirmed** → records the reviewer identity and the final
  outcome.

The **Audit** screen shows the full log with a live feed. The dev dashboard
(`/app/dev`) additionally shows real-time GPU utilisation, VRAM usage,
device temperature, Ollama model state and Surya warm-up status — so an
admin can always see whether the pipeline is genuinely working or quietly
stuck.

---

## 9. Technology stack

| Layer            | Choice                                              |
|------------------|-----------------------------------------------------|
| Backend language | Python 3.12                                         |
| Web framework    | FastAPI + Uvicorn (single worker, single process)   |
| Database         | PostgreSQL 16 (Docker, port `55432`)                |
| Migrations       | Alembic                                             |
| OCR              | **Surya 0.17+** (Foundation + Recognition + Detection predictors) |
| Classification   | **SigLIP 2** via `transformers` (`<5`)              |
| LLM extraction / rationale | **Gemma 4** via **Ollama** (`gemma4:31b`)   |
| GPU runtime      | PyTorch 2.11 (`cu128`) on NVIDIA A40                |
| Frontend         | React 18 + TypeScript + Vite + Tailwind CSS (dark)  |
| End-to-end tests | Playwright + pytest                                 |
| Logging          | structlog JSON                                      |
| Deploy           | `scripts/deploy.sh` → tmux session `claimsman`      |

---

## 10. Where to see it in action

Two recorded walk-throughs are produced by the scripts under `tests/` and
saved under `docs/visual-runs/` (gitignored — re-run locally to regenerate):

### Full claim flow

Script: `tests/demo_bg_bundle.py`
Output: `docs/visual-runs/claim-demo/`

A 23-beat narrated demo covering the full reviewer experience against a
real 6-document Bulgarian health-insurance bundle:

```
Епикриза · касов бон · фактура · рецептурна бланка · Амбулаторен лист
· Искане за възстановяване на разходи
```

Covers Inbox → New claim → drop zone → typing the form → Create → four-step
navigator → confidence polygons → thinking indicator → Gemma 4 rationale →
decision confirm → Add BBox → double-click edit → audit log → dev
dashboard → every Settings screen.

Artefacts: `video.webm`, 26 screenshots, `README.md`, `subtitles.srt`,
`subtitles.vtt`, `narration.txt`.

### Handwriting recovery (this one is the punchline)

Script: `tests/demo_handwriting.py`
Output: `docs/visual-runs/handwriting-demo/`

A 13-beat narrated demo that uploads _only_ the handwritten prescription
(`рецептурна бланка.pdf`), shows how Surya's unaided read of the "Nivalin
5 mg" line is unusable, and walks through the one-gesture recovery via
enforced bbox re-recognition.

The bbox geometry is not hard-coded by a human — it's computed by
rendering the PDF at the backend's exact scale (`2.0`, native page
pixels), localising the handwritten drug block via vertical ink-density
scan, and verifying visually. At runtime the demo reads the SVG's
`viewBox.baseVal` and `getBoundingClientRect()` and maps page pixels to
screen pixels; the resulting mouse drag lands precisely on the target
line.

Artefacts: `video.webm`, 13 screenshots, `README.md`, `subtitles.srt`,
`subtitles.vtt`, `narration.txt`.

---

## 11. Who it's for

- **Claims reviewers** who spend most of their day transcribing the same
  documents into spreadsheets.
- **Insurance operations managers** who need an audit trail deep enough
  to survive a regulator visit.
- **Compliance and legal** who can't send private documents to a
  third-party API.
- **Domain experts** who know the rules of their business cold and want
  to encode them in plain Python instead of a vendor DSL.
- **Engineering leaders** who are tired of running six services to do
  one job, and who want every moving part to live in one process on one
  box.

---

_Questions, feedback, or want to see a new domain pack wired up? Ping the
project owner, or jump straight to `tests/demo_handwriting.py` for the
shortest path from "raw scan" to "recovered text."_
