# Claimsman — Technical Specification

**Document status:** Draft v1.0
**Audience:** AI coding agent tasked with continuous, autonomous implementation of this project
**Language:** Everything in this spec, the code, the UI, and all artifacts MUST be in English.

---

## 0. How to Read This Document

This specification is the **entry point** for an agentic developer. Your job is to:

1. Read this spec in full.
2. Clone and **study the reference prototype** at `git@github.com:korobool/claims_doc_recognizer.git` in depth before writing any code. The prototype contains working OCR + LLM pipelines, YAML schema/domain systems, and UI patterns you should learn from and, where appropriate, lift.
3. Consult the **design reference** on Figma (`https://www.figma.com/design/f3DhieeDjuBClPTDKSlvWH/ClaimAI`) and the product site `https://claimsai.uk/` for UI/UX direction.
4. Build your own implementation plan, make architectural decisions, invent good UI/UX where the design reference is silent, and implement autonomously.
5. Deploy every iteration to the remote dev server (see §13), run it in `tmux`, and **visually test in a real browser** so the human reviewer can watch progress.
6. Evolve the test suite, skills, and documentation as the project grows — this is a continuous, agentic development task, not a one-shot build.

Where this spec and the prototype conflict, the spec wins. Where the spec is silent, use your judgment and document the decision in `docs/decisions/NNN-title.md` (ADR format).

---

## 1. Product Vision

**Claimsman** is a standalone claims management application for insurance (initially **health** and **motor**, extensible to other domains) that ingests a set of claim documents, understands them, reasons about them, and helps a human adjudicator make a payment decision.

It is a **new product**, not a fork of the prototype. The prototype proves the OCR + LLM extraction pipeline works; Claimsman productizes it and extends it into a full claim lifecycle tool with analysis, discrepancy detection, and decisioning.

### 1.1 Elevator Pitch
> Upload a claim bundle. Claimsman classifies every document, extracts structured fields per document schema and insurance domain, cross-checks the documents against each other for internal consistency and against domain rules for eligibility, flags anomalies and potential fraud signals, and produces a **proposed decision** (pay / partial pay / deny / request more info) with a full, auditable reasoning trail. A human reviewer then approves, edits, or rejects the decision with one click.

### 1.2 Core Value Propositions
- **Zero-config ingestion** — a single drop-zone accepts mixed bundles (PDFs, images, DOCX) including multi-page scans and machine-readable PDFs; Claimsman figures out the rest.
- **Domain-aware understanding** — schemas and domain contexts steer the LLM to extract the right fields and speak the right vocabulary (medical terminology, auto parts, repair codes, etc.).
- **Explainable decisions** — every decision carries a traceable reasoning chain: which field from which document, which rule, which LLM judgment. A reviewer can always see "why".
- **Human-in-the-loop by design** — Claimsman proposes; the human disposes. The UI is built around confident review, not forced automation.
- **Beautiful, fast UI** — the tool must feel polished. A clunky UI is a bug.

### 1.3 Non-Goals (v1)
- Claimsman is **not** a policy administration system, CRM, or billing system.
- No payment rail integration (no actual money movement). Claimsman outputs a decision; downstream systems execute it.
- No fine-tuning of custom OCR or LLM models. Use off-the-shelf Surya + Ollama Gemma 4.
- No mobile app. Responsive web only.
- No multi-tenant SaaS features (org isolation, billing, SSO) — v1 is single-tenant.

---

## 2. Reference Prototype

**Repo:** `git@github.com:korobool/claims_doc_recognizer.git`

**What the prototype does well (study and adapt):**
- **OCR pipeline** using **Surya OCR** (transformer-based, multilingual) — `app/services/ocr_service.py`.
- **Zero-shot document classification** using **SigLIP 2** — same file.
- **Deskew via Projection Profile Analysis** — `app/services/image_service.py`.
- **Document ingestion** supporting images, PDFs (with text-layer short-circuit), and DOCX — `app/services/document_service.py`.
- **LLM post-processing** against per-doc-type YAML schemas, with multimodal vision support via Ollama — `app/services/llm_service.py` (~1300 lines — read it carefully).
- **YAML schema and domain registries** — `app/config/schemas/*.yaml`, `app/config/domains/*.yaml`. Clean, extensible, elegant.
- **FastAPI + Uvicorn** backend structure — `app/main.py`, `app/routers/api.py`.

**What the prototype does not do (you must build):**
- Multi-document **claim assembly** — correlating fields across documents into a single claim object.
- **Consistency checking** — does the receipt amount match the prescription? Do the dates align? Is the provider on the policy's network?
- **Rule engine** / eligibility logic.
- **Decisioning** (pay / partial / deny / escalate) with reasoning trails.
- **Reviewer workflow** — queues, assignment, audit log.
- **Persistence** — the prototype is in-memory; Claimsman needs a real database.
- **Authentication** and access control.
- **Observability**, structured logs, metrics.
- **Production-quality UI** — the prototype UI is vanilla JS and minimal.

**Rule of thumb:** Reuse the OCR, image, document, schema, and domain services as inspiration and, where possible, as code lifted into Claimsman's `packages/` or `services/`. Rewrite or replace the router layer, the UI, and everything above the extraction stage.

---

## 3. Users & Personas

| Persona               | Goals                                               | Key Screens                                  |
|-----------------------|-----------------------------------------------------|----------------------------------------------|
| **Claims Reviewer**   | Review AI-proposed decisions; approve/edit/reject   | Inbox, Claim Detail, Decision Panel          |
| **Claims Uploader**   | Upload new claim bundles; monitor processing        | Upload, Processing Status                    |
| **Admin / Ops**       | Configure domains, schemas, LLM models; view system health | Settings, Schemas, Domains, System Status |
| **Auditor** (read-only) | Trace decisions for compliance                    | Claim Detail (read-only), Audit Log          |

For v1, all personas share one user account (no roles). Build the UI such that adding roles later is a `switch` statement, not a rewrite.

---

## 4. Functional Requirements

### 4.1 Claim Intake
- **F-1.1** The user can create a new claim by uploading one or more files (JPEG, PNG, TIFF, BMP, PDF, DOCX) via drag-and-drop or a file picker.
- **F-1.2** The user can optionally attach metadata at intake: claimant name, policy number, incident date, claim type (domain), notes.
- **F-1.3** The system auto-generates a claim ID and queues the bundle for processing.
- **F-1.4** During intake, the system distinguishes:
  - **Text-layer PDFs** → skip OCR, use embedded text.
  - **Scanned PDFs / images** → route through Surya OCR.
  - **DOCX** → extract text directly.
- **F-1.5** Multi-page PDFs are split into pages; each page is a unit of OCR + classification. A document can span multiple pages.

### 4.2 Document Understanding
- **F-2.1** Each page is deskewed (Projection Profile Analysis), OCR'd by **Surya — the one and only OCR engine used anywhere in Claimsman** — and classified by SigLIP 2 into one of the seeded `doc_type`s from §4.8.1 (extensible via YAML). No other OCR library or service is permitted: no Tesseract, EasyOCR, PaddleOCR, Apple Vision, AWS Textract, Google Document AI, Azure Read, or any cloud OCR. The only exception is the text-layer short-circuit (F-1.4) — reading an already-embedded text layer from a PDF or text from a DOCX is **not OCR** and is allowed.
- **F-2.2** Pages belonging to the same logical document (e.g., a 3-page medical form) are grouped. The grouping heuristic combines classification label continuity, page proximity, and LLM-based validation.
- **F-2.3** For each document, the LLM (Ollama Gemma 4, multimodal) extracts fields defined by the document's YAML schema, using the **active claim domain** (e.g., `health_insurance`, `motor_insurance`) to inject vocabulary and context into the prompt.
- **F-2.4** Extracted fields are typed (text, date, currency, number, list, person_name, address, phone, email) and each carries a **confidence**, a **source span** (bounding box + page ref), and an **LLM explanation**.
- **F-2.5** The reviewer can correct any extracted field inline; corrections are saved and feed back into an **audit trail**.
- **F-2.6 (Table extraction)** Structured tables (line items on receipts, labor/parts on repair estimates, prescription grids) are extracted as first-class repeated records, not as free text. The extractor emits each row as a typed object, preserves row order, ties each row to a bounding box region, and feeds the table totals into the consistency engine (§10). Lift the prototype's OCR+vision approach and extend it with a dedicated table pass when a schema field has type `list[object]`.
- **F-2.7 (Raw OCR correction)** The reviewer can **correct raw OCR text** before or after extraction runs. Clicking a recognized text box enters inline edit; saving the correction updates the OCR layer and, on request, re-runs the downstream extract stage for that document only (not the whole claim).
- **F-2.8 (Manual bounding boxes)** The reviewer can **draw a new bounding box** on a page in "Add BBox" mode, type the text it contains, and attach it to an existing field or leave it as a free annotation. Useful when Surya misses text (low-contrast stamps, handwriting, odd layouts).
- **F-2.9 (Confidence heatmap on bounding boxes)** Bounding boxes are color-coded by OCR/field confidence: red `< 0.80`, orange `0.80–0.93`, green `≥ 0.93`. The same palette is reused for extracted-field confidence dots in the fields panel, so the reviewer can scan a page and spot weak areas instantly.
- **F-2.10 (Multilingual OCR)** Claim documents may be in any language Surya supports (90+ languages). Language is auto-detected per page; the detected language is passed into the LLM prompt so extraction and rationales remain coherent. **The Claimsman UI itself stays English** (§5 i18n rule); only the document content is multilingual.
- **F-2.11 (Handwriting)** Handwritten content (doctor's notes, signatures, handwritten receipts) is routed through Surya's standard path — Surya handles handwriting reasonably out of the box. Low-confidence handwritten pages are flagged (`ocr_low_confidence`) so the reviewer can eyeball and correct them with F-2.7 / F-2.8.

### 4.3 Claim Assembly
- **F-3.1** The system synthesizes a **Claim** object from the extracted documents: claimant, policy, provider, incident, line items, totals, attached evidence.
- **F-3.2** Line items are derived from receipts / invoices / prescriptions; each line item points back to its source document and field.
- **F-3.3** Conflict resolution: if the same field appears in multiple documents (e.g., patient name on prescription and on medical form), the system prefers the higher-confidence source and flags any conflicts.

### 4.4 Consistency & Discrepancy Analysis
- **F-4.1** The system runs a **consistency check** across the assembled claim. Examples:
  - Does the receipt total equal the sum of its line items?
  - Do the prescription drug codes appear on the receipt?
  - Does the treatment date fall within the policy effective range?
  - Does the claimant's name match across documents?
  - Does the provider on the receipt match the prescribing doctor on the prescription?
- **F-4.2** Each check produces a `finding` with severity (`info`, `warning`, `error`), a message, and pointers to the offending fields.
- **F-4.3** The check set is **domain-specific** and lives in `app/domain_rules/<domain>.py`. Rules are Python functions, not a DSL, for v1.

### 4.5 Decisioning
- **F-5.1** The system produces a **proposed decision**: `approve`, `partial_approve`, `deny`, `needs_info`, with a numeric **recommended payout** (if applicable) and a list of **reasons**.
- **F-5.2** Decisioning uses a two-stage approach:
  1. **Deterministic rules** evaluate the claim against hard eligibility criteria (policy active, document completeness, no critical errors).
  2. **LLM reasoning** (Gemma 4) weighs the findings and extracted facts, returns a structured recommendation with a natural-language rationale.
- **F-5.3** The decision is **always** marked "proposed" until a human reviewer confirms it. The UI never auto-approves.
- **F-5.4** The reviewer can approve, edit (change decision or payout), or reject the AI proposal. Every action is audited (user, timestamp, before/after).

### 4.6 Review Workflow
- **F-6.1** Claims appear in an **Inbox** with status: `uploaded`, `processing`, `ready_for_review`, `under_review`, `decided`, `escalated`.
- **F-6.2** The reviewer can filter, sort, and open a claim to the **Claim Detail** view.
- **F-6.3** The **Claim Detail** view is the heart of the app (see §11). It presents: document thumbnails, extracted structured data, findings, proposed decision, action panel.
- **F-6.4** Once a decision is confirmed, the claim moves to `decided` and becomes read-only (edits create a new revision).

### 4.7 Configuration
- **F-7.1** Admins can manage **document schemas** (CRUD YAML) via UI and via files under `config/schemas/`. Changes hot-reload into the running process without a restart.
- **F-7.2** Admins can manage **domain packs** (CRUD YAML) via UI and via files under `config/domains/`. Hot-reload applies here too.
- **F-7.3** Admins can select the active **LLM model** from the Ollama models installed on the server (default `gemma4:latest`).
- **F-7.4** Admins can view system health: Ollama status, Surya status, device info (CPU/GPU), pipeline queue depth, in-flight stages.
- **F-7.5** Every domain has an **active flag**. Exactly one domain is active per claim (chosen at intake or auto-detected from document classifications).
- **F-7.6** Schemas and domains ship as **seeded defaults** on first run (see §4.8). Users can edit, clone, or delete them; resetting to defaults is a one-click action in the UI.
- **F-7.7 (Schema generation from a sample)** In the Schemas admin screen, an admin can upload a sample document and ask Claimsman to **propose a new schema**: run OCR + classification, then ask the LLM to suggest `fields: [...]` with types and descriptions. The admin reviews, edits, and saves the result as a new YAML under `config/schemas/`. This is an admin productivity feature, not a runtime feature.
- **F-7.8 (LLM model install / pull from the UI)** The System / LLM admin screen lists all Ollama models installed on the host and offers a "Pull new model" input that accepts a model tag (e.g., `gemma4:31b`, `llava:13b`) and **streams the Ollama pull progress** into the UI. Pulled models become selectable as the active model. Uninstall is **not** exposed in v1 (too easy to shoot the foot).
- **F-7.9 (Change active domain on an existing claim)** Before a decision is confirmed, the reviewer can switch a claim's active domain. Switching triggers a re-run from the `extract` stage onward (OCR and classification results are retained; only schema binding, extraction, assembly, analysis, and decisioning re-run). The prior run is archived as a claim revision.

### 4.8 Seeded Document Schemas & Domain Packs (Defaults)

Claimsman ships with a populated library of document schemas and two fully-configured domain packs covering **health insurance** and **motor insurance**. These are inserted on first run by `scripts/seed.py` from YAML files under `config/schemas/` and `config/domains/`. All of them are editable; none of them are hard-coded into services.

#### 4.8.1 Default Document Schemas (`config/schemas/*.yaml`)

Every schema defines: `doc_type`, `display_name`, `domains: [...]` (which domains it applies to), `fields: [...]` (name, label, type, required, description, examples), and optional `llm_hints`.

| `doc_type`          | Applies to           | Purpose                                 | Key fields                                                                                                                                    |
|---------------------|----------------------|-----------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `prescription`      | health               | Doctor's prescription                   | prescriber_name, prescriber_license, patient_name, patient_dob, issue_date, diagnosis_codes[], medications[{drug, dose, form, qty, refills, sig}] |
| `receipt`           | health, motor        | Proof-of-payment receipt                | provider_name, provider_address, receipt_number, issue_date, line_items[{description, qty, unit_price, total}], subtotal, tax, total, currency, payment_method |
| `invoice`           | health, motor        | Itemized invoice                        | issuer, bill_to, invoice_number, issue_date, due_date, line_items[], subtotal, tax, total, currency                                           |
| `medical_report`    | health               | Physician visit / diagnostic report     | patient_name, patient_dob, provider_name, visit_date, chief_complaint, findings, diagnoses[{code, description}], recommendations              |
| `discharge_summary` | health               | Hospital discharge summary              | patient_name, admission_date, discharge_date, attending_physician, diagnoses[], procedures[], medications_on_discharge[], follow_up           |
| `insurance_card`    | health, motor        | Member ID card (scan/photo)             | insurer_name, policy_number, member_name, group_number, effective_date, expiry_date, plan_type                                                |
| `repair_estimate`   | motor                | Body-shop estimate / quote              | shop_name, shop_address, estimate_number, date, vehicle{vin, make, model, year, plate, mileage}, labor_items[], parts_items[], subtotal, tax, total |
| `repair_invoice`    | motor                | Finalized repair invoice                | shop_name, invoice_number, date, vehicle{...}, labor_items[], parts_items[], subtotal, tax, total, payment_status                              |
| `police_report`     | motor                | Accident / incident report              | case_number, report_date, incident_date, location, parties[{name, role, license_number}], vehicles[{vin, plate, make, model, damage}], narrative, officer_name, officer_badge |
| `driver_license`    | motor                | Driver's license photo                  | full_name, license_number, dob, issue_date, expiry_date, class, jurisdiction, address                                                         |
| `vehicle_registration` | motor             | Vehicle registration certificate        | vin, plate, make, model, year, owner_name, registration_date, expiry_date, jurisdiction                                                       |
| `photo_of_damage`   | motor                | Damage photo (no structured fields)     | no fields extracted; the LLM produces a short natural-language `damage_description` and a severity hint (`minor`/`moderate`/`severe`)         |
| `correspondence`    | health, motor        | Letters, emails, free-form notes        | author, recipient, date, subject, body_summary                                                                                                |
| `unknown`           | all                  | Fallback when classification is unsure  | no fields; the LLM writes a short `summary` and a suggested `doc_type`                                                                         |

Each schema YAML also defines:
- **`llm_hints.system_preamble`** — short string prepended to the LLM prompt for this doc type.
- **`llm_hints.few_shot`** — optional in-file examples to steer extraction.
- **`validation`** — lightweight constraints (e.g., `total == sum(line_items.total)` within a tolerance). Validations feed the findings engine (§10.1).

#### 4.8.2 Default Domain Packs (`config/domains/*.yaml`)

A **domain pack** is a self-contained bundle of: description, vocabulary, required document set, rule module reference, prompt snippets, and default thresholds. Each claim is associated with exactly one active domain.

**`health_insurance.yaml`** — seeded default
- **Description:** "Private and public health insurance claims. Covers outpatient visits, prescriptions, hospital stays, and diagnostic procedures."
- **Vocabulary:** ICD-10 (diagnoses), CPT (procedures), NDC (drugs), common drug brand/generic names, medical abbreviations (`BP`, `HR`, `Rx`, `Dx`, `Hx`), units (`mg`, `mL`, `IU`), common form factors (tablet, capsule, injection, ointment).
- **Required docs (hard rule):** at least one of `{prescription, medical_report, discharge_summary}` AND at least one of `{receipt, invoice}` AND `insurance_card`.
- **Rule module:** `config/domain_rules/health_insurance.py` — ships with functions for `check_policy_active`, `check_patient_name_consistency`, `check_amount_matches_line_items`, `check_treatment_date_in_policy_window`, `check_drug_is_covered`, `check_provider_on_network` (stub — returns `info` if no network list configured).
- **Decision prompt snippet:** short description of what a reasonable health-insurance adjudicator weighs (medical necessity, policy coverage, exclusions, deductible, copay).
- **Default thresholds:** `low_confidence = 0.80`, `name_levenshtein_max = 2`, `amount_tolerance = 0.02`.

**`motor_insurance.yaml`** — seeded default
- **Description:** "Auto / motor insurance claims. Covers collision, comprehensive, third-party liability, and repair settlements."
- **Vocabulary:** VIN structure, common makes/models, body parts (`bumper`, `fender`, `quarter panel`, `A-pillar`), repair operation codes (R&I, R&R, refinish, blend), damage severity terms, at-fault terminology.
- **Required docs (hard rule):** `{police_report OR incident_statement}` AND `{repair_estimate OR repair_invoice}` AND `{driver_license}` AND `{insurance_card OR vehicle_registration}`.
- **Rule module:** `config/domain_rules/motor_insurance.py` — ships with `check_policy_active`, `check_vin_consistency_across_docs`, `check_plate_consistency`, `check_incident_date_in_policy_window`, `check_driver_is_policy_holder_or_named_driver`, `check_estimate_totals`, `check_photo_damage_severity_matches_estimate`.
- **Decision prompt snippet:** describes how an adjudicator weighs liability, at-fault status, prior claims, deductible, coverage caps, betterment.
- **Default thresholds:** `low_confidence = 0.80`, `name_levenshtein_max = 2`, `amount_tolerance = 0.05`.

#### 4.8.3 Extensibility

- **Adding a new domain** is a first-class, documented flow: drop a `config/domains/<code>.yaml` and a `config/domain_rules/<code>.py`, hit "Reload" in the admin UI (or restart), and the domain becomes selectable at intake.
- **Adding a new document type** is a YAML-only change: drop `config/schemas/<doc_type>.yaml`, declare which domains it belongs to, and the classifier's zero-shot label set picks it up on next reload. No Python code required for schema-only additions.
- **Editing a default** is safe: the seed script only inserts rows that don't already exist, so edits are preserved across deploys. A "Reset to defaults" admin action re-copies the shipped YAML on top of the active config (with a backup).
- **Domain rules that need custom code** live in `config/domain_rules/` as Python modules; the runtime imports them by domain code. This is intentionally not a sandboxed DSL — v1 trusts the admin writing the rules.
- **The UI exposes all of the above**: schemas and domains each get a dedicated admin screen with YAML editor, live validation, and a "Test against sample document" button that runs the LLM extraction against an uploaded file and shows the result.

### 4.9 Export & Interoperability

Claimsman's output is meant to be consumed by downstream systems (payment, ERP, claims-of-record). Every claim can be exported in the following forms from the Claim Detail view and via the API:

- **F-9.1 (Claim JSON)** `GET /api/v1/claims/{id}/export.json` returns a single JSON document containing: claim header, domain, all documents with all pages (OCR text, classification, confidence), all extracted fields (values, types, confidences, source bboxes, LLM rationales, corrections), findings, proposed and confirmed decisions with full rationale, audit trail, and schema/domain version stamps. This is the **canonical export** — every other format is derived from it.
- **F-9.2 (Line items CSV)** `GET /api/v1/claims/{id}/line_items.csv` flattens all line-item tables (receipt, repair estimate, etc.) into a single CSV for accounting workflows.
- **F-9.3 (Decision PDF)** `GET /api/v1/claims/{id}/decision.pdf` renders a reviewer-friendly one-page decision summary suitable for archiving or sharing externally (claim code, claimant, outcome, amount, reasons, date of decision, reviewer).
- **F-9.4 (Bundle ZIP)** `GET /api/v1/claims/{id}/bundle.zip` packages the original uploaded files + the Claim JSON + the Decision PDF into one archive.
- **F-9.5 (Import a previously exported claim)** `POST /api/v1/claims/import` accepts a Claim JSON from F-9.1 and reconstructs a claim with the same structure for debugging, test fixture creation, or seeding another environment. Import is admin-only.

The JSON shape is **versioned** (`"export_version": "1.0"`) so future format changes are non-breaking. Contract tests validate every export against a JSON Schema committed under `apps/web/schemas/export/`.

---

## 5. Non-Functional Requirements

| Category        | Requirement                                                                                     |
|-----------------|-------------------------------------------------------------------------------------------------|
| Performance     | Single-page OCR + extraction ≤ 10s on the dev server's hardware. Claim assembly ≤ 30s for a 10-page bundle. |
| Reliability     | Idempotent processing. Crashed jobs resume from the last completed stage.                       |
| Observability   | Structured JSON logs (`structlog`). Every pipeline stage emits a log line with `claim_id`, `stage`, `duration_ms`. |
| Security        | Authentication required for all routes. Uploaded files stored outside the web root. File-type validation via magic bytes, not just extension. |
| Privacy         | PII-aware logging: never log extracted field values at INFO level. Use DEBUG + redaction.        |
| Accessibility   | WCAG 2.1 AA for all primary screens (keyboard nav, focus rings, semantic HTML, contrast).       |
| Browser support | Latest Chrome, Firefox, Safari. No IE.                                                          |
| i18n            | English only for v1. All strings pulled from a single `locales/en.json`.                        |

---

## 6. System Architecture

### 6.1 High-Level

```
          ┌──────────────────────┐
          │       Browser        │
          │   (Claimsman SPA)    │
          └──────────┬───────────┘
                     │ HTTPS / JSON / WebSocket
                     ▼
    ┌───────────────────────────────────┐
    │        ONE PYTHON PROCESS         │
    │          (FastAPI + Uvicorn)      │
    │                                   │
    │  /api/v1/*   → JSON API           │
    │  /ws/*       → WebSocket          │
    │  /app        → built React SPA    │
    │                (static bundle)    │
    │  /app/assets → hashed JS/CSS      │
    │  /healthz    → liveness           │
    │                                   │
    │  In-process pipeline (ocr,        │
    │  vision, imaging, ingest,         │
    │  extract, assemble, analyze,      │
    │  decide) executed by an in-proc   │
    │  task runner (asyncio + thread-   │
    │  pool for CPU-heavy work).        │
    └──────┬─────────────┬──────────────┘
           │             │
           ▼             ▼
    ┌───────────┐  ┌───────────────┐
    │PostgreSQL │  │ Ollama (host) │
    │ (Docker,  │  │ Gemma 4       │
    │ custom    │  │ (already up)  │
    │  port)    │  └───────────────┘
    └───────────┘
```

### 6.2 Process Model — One Backend Process Serves Everything

**Hard rule:** Claimsman runs as **a single Python process** that serves both the backend API and the UI. There is **no separate frontend server, no separate worker process, no nginx in front of a Node dev server**. The one process:

- Exposes the JSON API under `/api/v1/*`.
- Exposes WebSocket events under `/ws/*`.
- Serves the **built** React SPA's static files under `/app` (HTML, hashed JS/CSS, assets). The root path `/` redirects to `/app`.
- Runs the ingestion and analysis pipeline **in-process**, using `asyncio` for I/O and a bounded `ThreadPoolExecutor` (or `ProcessPoolExecutor` where required by Surya/PyTorch) for CPU/GPU-bound stages.
- Writes to PostgreSQL (the only out-of-process dependency Claimsman manages).

**Rationale:** simplifies deploy, logs, and debugging on a single dev server; eliminates a queue/broker and an independent worker lifecycle; makes `tmux` monitoring trivial (one session, one process, one log stream). Scale-out is a v2 concern.

**Consequences the agent must respect:**
- The React app is **built** (Vite → static files) at deploy time and copied to `apps/web/static/app/`. FastAPI mounts that directory at `/app` with `StaticFiles(..., html=True)` so SPA routes resolve to `index.html`.
- In development, the agent **still builds** the frontend (Vite build, watch mode is fine) into the same static directory. **Do not** run `vite dev` on a separate port in production — there is one process and one port.
- Long-running pipeline stages must not block the event loop: wrap CPU-heavy work in `run_in_executor` and yield back so API requests and WebSocket events continue flowing.
- Surya OCR and SigLIP 2 models load **lazily on first use** and stay in memory for the process lifetime (same pattern as the prototype).
- **Ollama is already running on the host** (Gemma 4 pulled). Claimsman's single process connects to `http://localhost:11434` over HTTP. Do not provision or containerize Ollama.
- Postgres runs in Docker on a custom port (see §13). It is the only external service Claimsman's process depends on.

### 6.3 Pipeline as Stages

Every claim moves through stages, executed **in-process** by the task runner (an `asyncio` orchestrator that dispatches CPU/GPU-heavy stages to an executor). Each stage is resumable: stage transitions are persisted to Postgres so a process restart picks up where it left off.

1. `ingest` — persist files, split PDFs, create Page rows.
2. `normalize` — deskew, enhance contrast if needed.
3. `ocr` — Surya OCR per page (skip if text layer is present and long enough).
4. `classify` — SigLIP 2 per page.
5. `group` — cluster pages into logical documents.
6. `extract` — run LLM per document with schema + domain prompt.
7. `assemble` — build the Claim object.
8. `analyze` — run consistency checks, produce findings.
9. `decide` — propose a decision + rationale.
10. `ready_for_review` — transition to reviewer inbox.

Stages emit **WebSocket events** on `/ws/claims/{id}` so the UI live-updates the processing status. The task runner lives in `apps/web/pipeline/runner.py` (or equivalent) and is started from the FastAPI lifespan hook — no standalone worker entry point.

---

## 7. Technology Stack

### 7.1 Required
| Layer         | Choice                                 | Rationale                                                        |
|---------------|----------------------------------------|------------------------------------------------------------------|
| Language      | Python 3.12                            | Matches prototype; rich ML ecosystem.                            |
| Web framework | FastAPI + Uvicorn                      | Matches prototype; async-native; type-safe.                      |
| OCR           | Surya OCR                              | Prototype-proven; multilingual; transformer-based.               |
| Classification| SigLIP 2 (transformers)                | Prototype-proven; zero-shot.                                     |
| LLM           | **Ollama with Gemma 4** (host-installed)| Required; vision-capable; already running on the dev server.     |
| DB            | PostgreSQL 16                          | Relational, mature, JSONB for semi-structured claim data.        |
| Pipeline runner | In-process asyncio + executor        | Single-process mandate — no Celery/RQ/Redis broker.              |
| Frontend      | React 18 + TypeScript + Vite (build only) | Built to static files and served by FastAPI at `/app`.         |
| UI toolkit    | Tailwind CSS + shadcn/ui               | Rapid, beautiful, accessible components.                         |
| State         | TanStack Query + Zustand               | Server cache + minimal client state.                             |
| Charts        | Recharts                               | Simple declarative charts.                                       |
| Logging       | structlog                              | Structured JSON logs out of the box.                             |
| Testing       | pytest (backend), Playwright (e2e/visual) | Matches the prototype's testing style; visual mode supported.    |
| Linting       | ruff + mypy (py), eslint + prettier (ts) | Fast, consistent.                                                |
| Packaging     | uv (py), pnpm (js)                     | Fast, modern.                                                    |

### 7.2 Discouraged / Forbidden
- No Django. No Flask.
- No mock database in integration tests (see §14).
- No vanilla JS for the UI.
- No OpenAI or Gemini calls in v1 — all LLM traffic goes to the local Ollama.
- **No separate frontend server process** in any environment. Vite builds to static files; FastAPI serves them. `vite dev` on a standalone port is forbidden on the deployed server.
- **No Celery, no RQ, no Redis, no standalone worker process.** The pipeline runs inside the same Python process as the API.
- **No OCR engine other than Surya.** Tesseract, EasyOCR, PaddleOCR, Apple Vision, AWS Textract, Google Document AI, and Azure Read are forbidden. If a document fails Surya, fix the preprocessing (contrast, deskew, DPI) and retry — do not reach for a different OCR.

---

## 8. Data Model (PostgreSQL)

Names are indicative; the agent may refine casing and add fields. All tables have `id`, `created_at`, `updated_at`.

```
users             (id, email, display_name, password_hash, role)
claims            (id, code, title, claimant_name, policy_number, domain, status,
                   created_by, assigned_to, proposed_decision_id, final_decision_id)
uploads           (id, claim_id, filename, mime_type, size_bytes, storage_path, sha256)
documents         (id, claim_id, doc_type, display_name, source_pages[])
pages             (id, upload_id, page_index, image_path, ocr_text, classification,
                   confidence, bbox_json, text_layer_used)
extracted_fields  (id, document_id, schema_key, value_json, confidence, source_bbox_json,
                   llm_model, llm_rationale, corrected_by, corrected_at)
findings          (id, claim_id, severity, code, message, refs_json)
decisions         (id, claim_id, kind, outcome, amount, rationale_md, is_proposed,
                   created_by, confirmed_by, confirmed_at)
audit_log         (id, actor_id, entity, entity_id, action, before_json, after_json)
schemas           (id, doc_type, yaml_content, active)
domains           (id, code, yaml_content, active)
```

Notes:
- `claim.status` uses the enum from §4.6.
- `extracted_fields.value_json` stores typed values; the type is resolved by joining against the active schema.
- `decisions` stores both proposed and confirmed decisions; the `is_proposed` flag distinguishes them. A claim may have many rows (revision history); the latest non-proposed confirmed is the "current" decision.
- Store uploads on the local filesystem under `/var/lib/claimsman/uploads/<claim_id>/<sha256>.<ext>` for v1; S3-compatible storage is a v2 concern.

---

## 9. API Surface (indicative)

All routes under `/api/v1`. JSON in, JSON out. Auth via session cookie or bearer token (pick one).

```
POST   /auth/login
POST   /auth/logout
GET    /auth/me

GET    /claims                     # list with filters
POST   /claims                     # create claim shell
GET    /claims/{id}                # full claim detail
PATCH  /claims/{id}                # update metadata
DELETE /claims/{id}                # (soft-delete, admin only)

POST   /claims/{id}/uploads        # multipart upload
POST   /claims/{id}/process        # (re)trigger pipeline
GET    /claims/{id}/events         # WebSocket — live stage updates

GET    /claims/{id}/documents
GET    /documents/{id}
PATCH  /documents/{id}/fields/{key}  # manual correction

GET    /claims/{id}/findings
GET    /claims/{id}/decision       # proposed decision + rationale
POST   /claims/{id}/decision       # reviewer confirms/edits
POST   /claims/{id}/reopen         # revert to under_review

GET    /schemas
PUT    /schemas/{doc_type}
GET    /domains
PUT    /domains/{code}

GET    /system/health
GET    /system/llm/models
```

---

## 10. Claim Analysis & Decisioning

### 10.1 Findings Catalog (examples, extend as needed)
| Code                    | Severity | Check                                                        |
|-------------------------|----------|--------------------------------------------------------------|
| `missing_required_doc`  | error    | Domain requires doc type X; none present.                    |
| `name_mismatch`         | warning  | Claimant name differs across documents beyond a Levenshtein threshold. |
| `amount_mismatch`       | error    | Sum of line items ≠ total on receipt.                        |
| `date_out_of_policy`    | error    | Treatment date outside policy effective window.              |
| `provider_unknown`      | warning  | Provider not found in known list (if a list is configured).  |
| `duplicate_upload`      | warning  | SHA256 of an upload matches an earlier claim's upload.       |
| `ocr_low_confidence`    | info     | Any field with confidence < threshold.                        |
| `llm_uncertain`         | info     | LLM marked extraction as uncertain.                          |
| `domain_rule_violation` | varies   | Domain-specific rule fired (e.g., drug not covered).         |

### 10.2 Decisioning Flow
1. Hard gates: if any `error`-severity finding blocks payout → `deny` or `needs_info`.
2. Soft judgment: LLM receives the assembled claim (JSON), the findings list, and the domain description; returns:
   ```json
   {
     "outcome": "approve|partial_approve|deny|needs_info",
     "amount": 0.0,
     "rationale": "markdown...",
     "confidence": 0.0
   }
   ```
3. A deterministic post-processor cross-checks the LLM's `amount` against line items and caps it at the claim total.
4. The result is persisted as a proposed decision.

The prompt template for decisioning lives in `app/prompts/decision.jinja` and must be versioned — every prompt change bumps a version and is logged against the decision.

---

## 11. UI / UX Specification

### 11.1 Principles
1. **Reviewer-first.** The most common user path — "open a claim, review, decide" — must be buttery smooth and keyboard-driven.
2. **Explainability surfaces everywhere.** Every extracted field shows its source on hover. Every finding links to the offending evidence. Every proposed decision shows its reasoning trail.
3. **No surprises.** Long-running operations have progress bars, not spinners. Errors are actionable, not cryptic.
4. **Beautiful by default.** Generous whitespace, a considered type scale, a calm color palette (neutral base + one accent for action, plus semantic colors for severity). Dark mode is first-class, light mode is supported.

### 11.2 Complete Screen Inventory

The Figma reference covers general look-and-feel but **does not cover every screen Claimsman needs** (see §11.5). Use Figma's visual language — typography, spacing, color palette, component shapes — as the style baseline, then design every screen below in that language. Commit screenshots of every major UI iteration to `docs/screenshots/` so progress is visible.

#### Authentication & Shell
1. **Login** — email + password, error states for wrong credentials, rate-limit notice.
2. **App shell** — persistent nav (Inbox, New Claim, Audit, Settings), user menu, environment badge, global search (`/`), keyboard-shortcut help (`?`).

#### Claim lifecycle
3. **Inbox** — virtualized table of claims. Columns: code, claimant, domain, status pill, stage (if processing), amount, last activity, assignee. Filters: status, domain, date range, assignee, free-text. Saved views. Bulk select → bulk reassign/archive. Live badge for claims ready for review.
4. **New Claim / Upload** — drop zone, metadata form (claimant, policy number, incident date, domain, notes), per-file upload progress list with status (queued, uploading, ingesting, ocr, classify, extract, done, error), cancel per file, retry per file.
5. **Claim Processing** (transitional) — appears after upload while the pipeline runs. Live stage progress for all ten stages from §6.3, streamed over `/ws/claims/{id}`. Not a blocking modal: the user can navigate away and come back.
6. **Claim Detail** — the main workspace. Resizable three-pane layout:
   - **Left rail:** document tree (documents → pages), thumbnails with classification label and color-coded confidence. Reorder by drag. Click to focus a page. Page actions: reject, replace, move to another document, regroup.
   - **Center (page viewer):** zoomable/pannable page image with bounding-box overlay, confidence heatmap toggle, "Add BBox" tool, "Edit OCR text" tool, "Deskew again" action, page rotation, language indicator, before/after view for normalization.
   - **Center (fields panel, split with viewer):** extracted fields form driven by the active schema; inline edit; hover-link bi-directionally with bounding boxes; per-field confidence dot; per-field LLM rationale popover; "Re-extract this document" action; line-item tables with add/remove/edit rows and per-row bbox.
   - **Right rail:** findings list (grouped by severity), proposed decision card (outcome, amount, rationale as markdown, confidence), action buttons (Approve, Edit, Reject, Request Info), quick links to export menu and revision history.
   - **Top bar:** claim code + title, status pill, domain selector (triggers §4.7 F-7.9 re-run confirm modal), assignee, export menu, audit button.
7. **Decision Edit modal** — invoked by "Edit" on the proposed decision. Form for outcome, amount, and reviewer rationale (markdown). Shows a diff between the AI proposal and the reviewer's edits before confirm.
8. **Revision History** — timeline of every run/decision for a claim (each re-extract, each domain switch, each decision revision) with diff view and "restore this revision" for admins.
9. **Request Info flow** — compose an info request (what's missing, free text), attach to claim, transitions claim to `needs_info`. No email sending in v1; the request is captured on the claim.

#### Admin / Settings
10. **Settings → Schemas** — list of schemas with doc_type, display name, applicable domains, edit button. Detail: YAML editor with live validation, field table view, "Test against sample document" panel (upload a file → run OCR + classify + LLM extract with this schema → show result side-by-side with raw OCR), clone, delete, **reset to default**.
11. **Settings → Schemas → Generate from sample** (F-7.7) — upload a sample doc, OCR runs, LLM proposes a schema, admin reviews a diff-style editor, edits, saves as new `doc_type`.
12. **Settings → Domains** — list of domain packs. Detail: YAML editor, vocabulary chips, required-document-set visualizer, link to the Python rule module with the list of exported check functions, threshold sliders, "active/inactive" toggle, "Test against a sample claim" runner. Reset to default.
13. **Settings → LLM** — list of Ollama models installed on the host with size, last used, vision-capable badge. "Pull new model" input with streaming progress bar (F-7.8). Active model selector per use case (extraction, decisioning — can be the same model). Temperature and token budget fields.
14. **Settings → Health** — Ollama status, Surya status (loaded/not loaded, model version), device info (CPU/GPU/MPS), memory, pipeline queue depth, in-flight stages, recent errors.
15. **Settings → Users** (v1: single admin) — stub screen showing the current user; room to grow into full user management without re-architecting the shell.

#### Audit & export
16. **Audit Log (global)** — filterable timeline across all claims; actor, action, target, before/after diff.
17. **Export menu** (per claim, from the top bar) — JSON, line-items CSV, decision PDF, bundle ZIP (F-9.1–9.4).
18. **Import a claim** (admin) — upload a previously exported Claim JSON; show a preview diff and confirm (F-9.5).

#### Help & onboarding
19. **Keyboard shortcuts cheat sheet** — modal triggered by `?`.
20. **Empty states** for every list screen (Inbox, Audit, Schemas, Domains, Models) with a call-to-action.
21. **Error states** — dedicated layouts for: Ollama unreachable, LLM model not pulled, Surya model not loaded, pipeline stalled, upload rejected (wrong MIME / too large). Each error tells the reviewer what to do next, not just what went wrong.

### 11.3 Interaction Details
- **Drag-and-drop** upload with file-type preview, magic-byte validation, and per-file cancel/retry.
- **Live pipeline events** over WebSocket drive a stage progress bar (Ingest → Normalize → OCR → Classify → Group → Extract → Assemble → Analyze → Decide → Ready). Each stage shows duration and errors inline.
- **Zoom & pan** on the page viewer (mouse wheel, pinch, double-click to fit, `+`/`-` keys).
- **Resizable panes** (drag the splitters between left/center/right; remember user preference in localStorage).
- **Hover-link**: hovering a field highlights its bounding box on the page image, and vice versa. Also scrolls the counterpart into view.
- **Bounding-box toolbox** on the page viewer: Select, Add BBox, Edit OCR text, Delete BBox, Toggle confidence heatmap, Toggle raw vs corrected OCR.
- **Line-item table editor** — inline row add/delete/reorder; each row shows a tiny source-bbox chip that jumps the viewer on click.
- **Drag to regroup pages** across documents in the left rail; drop into "New document" zone to split.
- **Domain switch** on the top bar opens a confirm modal that lists exactly which stages will re-run (extract, assemble, analyze, decide).
- **Keyboard shortcuts**: `j`/`k` next/prev (inbox and claim-local page nav), `a` approve, `e` edit, `r` reject, `n` needs-info, `/` focus search, `?` shortcut help, `g i` inbox, `g s` settings, `esc` close modal.
- **Command palette** (`⌘K` / `Ctrl K`) — jump to any claim by code, open any settings screen, run any of the top actions.
- **Toasts** for non-modal feedback; modals only for destructive or scope-changing confirms.
- **Skeleton loaders** everywhere (no layout shift). Optimistic updates where safe.
- **Markdown renderer** for AI rationales and reviewer notes (safe-subset only).
- **Language indicator** on every page that shows the auto-detected language with a short label (e.g., `uk` / `Ukrainian`).

### 11.4 Design Reference — What's Covered and What Isn't

The **Figma design** (`https://www.figma.com/design/f3DhieeDjuBClPTDKSlvWH/ClaimAI?node-id=8640-611`) and the **ClaimsAI product site** (`https://claimsai.uk/`) are **partial, stylistic references only**. Use them for:
- Overall visual language (typography scale, spacing, palette, radius, shadow depth, button style).
- General flow for the common reviewer path (inbox → claim → decision).
- High-level IA cues for where things live.

They are **not** a complete design and they **do not cover** most of Claimsman's functional surface. Where Figma is silent, **you must design from scratch** in Figma's visual language, document the decision under `docs/decisions/`, and commit a screenshot under `docs/screenshots/` for human review.

### 11.5 Screens & Components You Must Design Yourself

The following list enumerates screens, panels, and components that are **likely absent or incomplete** in the Figma reference. Treat it as a design backlog: for each item, produce a working UI in the app, capture a screenshot, and log a short ADR if you made a notable taste call.

- **Login** screen.
- **Global app shell** with command palette (`⌘K`) and keyboard shortcut help overlay.
- **Claim Processing** live view (all ten pipeline stages from §6.3 streaming live).
- **Raw OCR text inline-edit tool** on the page viewer (F-2.7).
- **"Add BBox" manual bounding box tool** including crosshair cursor, rectangle drag, text input overlay, confirm/cancel (F-2.8).
- **Confidence heatmap toggle + legend** (red/orange/green bands per F-2.9).
- **Line-item table editor** inside the fields panel (F-2.6), with per-row source bbox chips.
- **Page actions** menu: reject page, replace page, rotate, deskew again, move to another document, regroup pages.
- **Document regrouping** drag-and-drop in the left rail.
- **Domain switch** confirmation modal listing stages that will re-run (F-7.9).
- **Decision Edit modal** showing a diff between the AI-proposed decision and the reviewer's edits.
- **Revision History** timeline with diffs and admin-only restore.
- **Findings panel** grouped by severity with click-to-source jump and severity-band totals.
- **Proposed Decision card** including outcome pill, amount, confidence, markdown rationale, and a breakdown of which findings drove it.
- **Request Info** composer (no external delivery — captures on the claim).
- **Settings → Schemas** YAML editor + **"Test against sample"** panel (F-7.1).
- **Settings → Schemas → Generate from sample** flow (F-7.7).
- **Settings → Domains** YAML editor + vocabulary chips + rules-module viewer + threshold sliders + "test sample claim" runner (F-7.2).
- **Settings → LLM** model list with **streaming pull-progress bar** (F-7.8).
- **Settings → Health** panels (Ollama / Surya / device / queue / errors) (F-7.4).
- **Settings → Users** stub (forward-compatible shell).
- **Audit Log (global)** — timeline with actor/action/target/diff.
- **Export menu** (per claim) and **Import a claim** (admin) (F-9.1–9.5).
- **Empty states** for Inbox, Audit, Schemas, Domains, Models, Settings → Users.
- **Error states** for Ollama unreachable, model not pulled, Surya not loaded, pipeline stalled, upload rejected.
- **Accessibility layer** — focus ring styling, skip links, ARIA roles for the non-standard bounding-box canvas, screen-reader announcements for live pipeline updates.
- **Keyboard shortcut cheat sheet** modal.
- **Markdown renderer** with a safe subset for AI rationales and reviewer notes.
- **Language indicator** chips per page.

Some of these may already exist in Figma in some form; if you spot them there, lift the visual treatment. Otherwise, design them. Either way, screenshot every one into `docs/screenshots/<milestone>/<screen>.png` and record tradeoffs in ADRs when the decision isn't obvious.

---

## 12. Project Layout

```
claimsman/
├── apps/
│   ├── web/                          # The single Python process
│   │   ├── main.py                   # FastAPI app, lifespan, mounts
│   │   ├── routers/                  # /api/v1/* route modules
│   │   ├── ws/                       # /ws/* WebSocket handlers
│   │   ├── models/                   # SQLAlchemy
│   │   ├── schemas/                  # Pydantic
│   │   ├── services/                 # Business services
│   │   ├── pipeline/                 # In-process stage runner
│   │   │   ├── runner.py
│   │   │   └── stages/
│   │   ├── prompts/                  # Jinja templates for LLM
│   │   ├── static/
│   │   │   └── app/                  # BUILT React SPA (Vite output) — mounted at /app
│   │   └── tests/
│   └── frontend/                     # React + Vite source (build-only; no dev server in prod)
│       ├── src/
│       ├── public/
│       ├── vite.config.ts            # outDir → ../web/static/app
│       └── tests/                    # Playwright e2e + component tests
├── packages/
│   ├── ocr/                # Surya wrapper (lift from prototype)
│   ├── vision/             # SigLIP classifier
│   ├── imaging/            # Deskew, normalize
│   ├── ingest/             # PDF/DOCX extraction
│   ├── extract/            # LLM extraction + schema binding
│   ├── assemble/           # Claim assembly
│   ├── analyze/            # Findings rules
│   └── decide/             # Decisioning engine
├── config/
│   ├── schemas/            # YAML doc schemas — seeded defaults (see §4.8.1)
│   │   ├── prescription.yaml
│   │   ├── receipt.yaml
│   │   ├── invoice.yaml
│   │   ├── medical_report.yaml
│   │   ├── discharge_summary.yaml
│   │   ├── insurance_card.yaml
│   │   ├── repair_estimate.yaml
│   │   ├── repair_invoice.yaml
│   │   ├── police_report.yaml
│   │   ├── driver_license.yaml
│   │   ├── vehicle_registration.yaml
│   │   ├── photo_of_damage.yaml
│   │   ├── correspondence.yaml
│   │   └── unknown.yaml
│   ├── domains/            # YAML domain packs — seeded defaults (see §4.8.2)
│   │   ├── health_insurance.yaml
│   │   └── motor_insurance.yaml
│   └── domain_rules/       # Python rule modules — one per domain
│       ├── health_insurance.py
│       └── motor_insurance.py
├── deploy/
│   ├── docker-compose.yml  # Postgres only (web runs natively in tmux)
│   └── systemd/            # optional unit files
├── docs/
│   ├── decisions/          # ADRs
│   ├── screenshots/
│   └── runbook.md
├── scripts/
│   ├── bootstrap.sh
│   ├── seed.py
│   └── visual-test.sh
└── task/
    ├── input.md            # (given)
    └── SPEC.md             # (this document)
```

---

## 13. Deployment & Infrastructure

### 13.1 Dev/Test Server
- **SSH:** `ssh administrator@108.181.157.13` (key-based; password stored in the task brief for sudo if prompted).
- **Project directory:** create `~/workspace/claimsman` on the server and check out the repo there.
- **Ollama:** already installed and running on the host; **Gemma 4 is already pulled**. Do not reinstall. Claimsman's backend connects over `http://localhost:11434` on the host.
- **Database:** PostgreSQL in Docker on a **non-default port** (e.g., `55432`). Do not collide with any other Postgres on the host.
- **Claimsman web process:** runs natively (not in Docker) inside a `tmux` session (`tmux new -s claimsman`) so logs are persistent and the reviewer can attach. One `tmux` session, one `python -m apps.web` (or `uvicorn apps.web.main:app`) command, one log stream.
- **No separate worker session.** The pipeline runs inside the web process (see §6.2).
- **Port exposure:** bind the Claimsman web server to a custom host port (e.g., `8811`) so it can be reached in a browser as `http://108.181.157.13:8811/app`.
- `deploy/docker-compose.yml` contains **only Postgres** (and optional adminer for debugging). Bring it up with `docker compose -f deploy/docker-compose.yml up -d`.
- **DO NOT** run Ollama inside Docker. Use the one already on the host.

### 13.2 Release Flow
1. Commit to `main` on GitHub (`git@github.com:korobool/claimsman.git`). **Never push `task/input.md`** — it is in `.gitignore` and contains sensitive material.
2. On the server, `git pull` inside `~/workspace/claimsman`.
3. Run `scripts/deploy.sh` which:
   - Ensures Postgres is up (`docker compose up -d`).
   - Installs/updates Python deps (`uv sync` or `pip install -r requirements.txt`).
   - Installs frontend deps and **builds** the SPA to `apps/web/static/app/` (`pnpm build`).
   - Runs DB migrations (`alembic upgrade head`).
   - Restarts the single `claimsman` tmux session running the web process.
4. Smoke test with `scripts/visual-test.sh` (Playwright visual mode — see §14).

### 13.3 Config
- One `.env` file on the server; committed template at `deploy/.env.example`.
- Secrets never in git.

---

## 14. Continuous Agentic Development & Testing

This is not a "build once and hand over" project. It's a **continuous agentic loop**: plan → implement → deploy → **visually test** → observe logs → fix → repeat. The agent must:

### 14.1 Visual Testing in the Browser (Required)
- Every meaningful change runs a **Playwright test suite in visual (headed) mode** against the deployed instance on the dev server.
- Test scripts are committed under `apps/frontend/tests/visual/` and `scripts/visual-test.sh`.
- The suite walks real user flows: sign in, upload a bundle, wait for pipeline completion, open the claim detail, hover fields, approve, audit log entry.
- Screenshots/videos are archived to `docs/visual-runs/<timestamp>/` on every run so the human can scrub progress.
- Test data lives under `test_assets/` (lift the prototype's `tests/assets/scanned_multipage_claim.pdf` to start).

### 14.2 Evolving Test Suite
- The test suite is not frozen — **it grows with the product**. New feature → new test. Bug found → regression test. The spec explicitly requires this.

### 14.3 Logs & Observability
- Backend logs to stdout as JSON, captured by the `tmux` session.
- `scripts/logs.sh` tails the current session.
- On a failing test, the agent **must** read the server logs, diagnose, fix, and re-run. Do not guess.

### 14.4 Loop Discipline
- **No silent failures.** If a deploy fails, roll back to the last known-good commit and open a decision doc (`docs/decisions/NNN-rollback-why.md`).
- **No destructive ops on the server** without documenting them first.
- **No skipping visual tests** just because unit tests pass.

### 14.5 Unit & Integration Tests
- **Backend**: pytest for services, with fakes for Ollama and Surya but **real Postgres** (Dockerized test DB).
- **Frontend**: component tests with Vitest + Testing Library.
- **Contract**: generated OpenAPI schema validated against the backend in CI.

---

## 15. Security

- All API routes require authentication except `/auth/login`, `/system/health`.
- Passwords hashed with argon2id.
- File uploads: enforce allowlist of MIME types; verify magic bytes with `python-magic`; cap size at 50 MB/file, 500 MB/bundle.
- Store files outside the web root; serve via authenticated route only.
- No SQL string interpolation anywhere — SQLAlchemy Core/ORM only.
- CSRF protection on session-based auth.
- Security headers: HSTS, CSP, X-Frame-Options, X-Content-Type-Options.
- Rate-limit login and upload endpoints.
- Dependency scanning (`pip-audit`, `npm audit`) on every push.

---

## 16. Milestones

| Phase | Outcome                                                                                          |
|-------|--------------------------------------------------------------------------------------------------|
| M1    | Skeleton: repo, docker-compose DB/Redis, FastAPI + React scaffolds, login, single-file upload, health check, CI green. Deployed and reachable on the dev server. |
| M2    | Ingest → OCR (Surya) → Classify (SigLIP) → Page viewer with bounding boxes. Lifted from prototype, wrapped in Claimsman services, visible in the UI. |
| M3    | Seed script installs all default schemas (§4.8.1) and both domain packs (§4.8.2) on first run. LLM extraction (Gemma 4) with YAML schemas + domains. Editable extracted fields. Claim assembly from multiple documents. |
| M4    | Findings engine + domain rule modules (health, motor) with the seeded check sets from §4.8.2. Findings shown in UI with source highlights. |
| M5    | Decisioning engine (hard gates + LLM). Proposed decision panel. Reviewer approve/edit/reject flow with audit trail. |
| M6    | Admin UIs for schemas (YAML editor + "Test against sample"), domains (YAML editor + rules module link), LLM model selection, "Reset to defaults" action. System health page. |
| M7    | Polish pass: accessibility, performance, keyboard shortcuts, empty states, screenshots, docs.    |

Each milestone ends with a green visual test run and a screenshot set committed under `docs/screenshots/M<n>/`.

---

## 17. Acceptance Criteria

Claimsman v1 is "done" when **all** of the following are true:

1. A reviewer can sign in, upload a multi-page mixed bundle, watch the pipeline complete in real time, review the assembled claim with full source traceability, and confirm a decision — all in a browser, on the dev server, in under five minutes total including pipeline time.
2. The health-insurance demo bundle produces a correctly classified and extracted claim with **zero manual pre-processing**.
3. A deliberate discrepancy in the demo bundle (e.g., mismatched amounts) produces a matching finding and shifts the proposed decision to `needs_info` or `partial_approve`.
4. All Playwright visual tests pass on the dev server in headed mode.
5. `docs/runbook.md` contains complete, accurate run/deploy/debug instructions.
6. An auditor can trace any decision back to the exact page and bounding box of every piece of evidence.
7. The UI passes an accessibility audit (axe-core) with zero critical issues on every primary screen.

---

## 18. Open Questions for the Agent

These are explicitly left for you to decide and document in `docs/decisions/`:

- In-process task runner design: a single `asyncio` orchestrator vs. a small in-process job table polled by a background task group. (Pick one, respect §6.2.)
- Session cookies vs. JWT for auth.
- Which React component library variant (shadcn/ui vs. Radix primitives from scratch).
- Storage structure for the visual test archive (flat by timestamp vs. nested by claim ID).
- Whether to ship a seeded demo dataset inside the repo or fetch it on first run.

Document the decision, the alternatives considered, and the reasoning. Don't ask the human — decide, record, and move on.

---

## 19. References

- **Reference prototype:** `git@github.com:korobool/claims_doc_recognizer.git`
- **Design reference:** Figma — `https://www.figma.com/design/f3DhieeDjuBClPTDKSlvWH/ClaimAI?node-id=8640-611`
- **Product reference:** `https://claimsai.uk/`
- **Surya OCR:** `https://github.com/VikParuchuri/surya`
- **Ollama Gemma 4:** already installed on the dev server
- **Dev server:** `ssh administrator@108.181.157.13` — workspace at `~/workspace/claimsman`
- **Task input (original brief):** `task/input.md`

---

## Appendix A — Initial ADR Template

```markdown
# ADR-NNN: <Title>

- **Status:** proposed | accepted | superseded
- **Date:** YYYY-MM-DD
- **Deciders:** (agent)

## Context
What is the issue that we're seeing that is motivating this decision?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or more difficult to do because of this change?

## Alternatives Considered
What other options did we weigh, and why did we discard them?
```
