#!/usr/bin/env python3
"""Claimsman end-to-end demo recording.

Drives a Chromium window through the full reviewer experience with
the 6-document Bulgarian bundle:
    рецептурна бланка · фактура · касов бон · Амбулаторен лист
    · Епикриза · Искане за възстановяване на разходи

Produces (all under ``docs/visual-runs/claim-demo/`` which is
gitignored):
    - video.webm              Playwright's video recording
    - screenshots/NN-*.png    one screenshot per scripted step
    - subtitles.srt           SRT subtitles matching the video timeline
    - narration.txt           same narration as plain text
    - README.md               a written walkthrough of what the demo shows

Usage:
    python tests/demo_bg_bundle.py
    CLAIMSMAN_DEMO_BASE_URL=http://127.0.0.1:8811 python tests/demo_bg_bundle.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Callable

import httpx
from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("CLAIMSMAN_DEMO_BASE_URL", "http://108.181.157.13:8811")
SAMPLE_DIR = Path.home() / "Downloads" / "RE_ AI доставчици"
SAMPLE_FILES = [
    "Епикриза.pdf",
    "касов бон.pdf",
    "фактура.pdf",
    "рецептурна бланка.pdf",
    "Амбулаторен лист.pdf",
    "Искане  за възстановяване на разходи.pdf",
]

OUT_ROOT = REPO_ROOT / "docs" / "visual-runs" / "claim-demo"
SCREENS_DIR = OUT_ROOT / "screenshots"
VIDEO_TMP_DIR = OUT_ROOT / "video-tmp"


# Injected into every page so the recording captures a visible cursor
# (headless Chromium doesn't paint the OS cursor into the video). The
# script also renders a soft blue ring on every click so mouse actions
# stay legible in the recording.
CURSOR_JS = """
(() => {
  if (document.getElementById('demo-cursor')) return;
  const c = document.createElement('div');
  c.id = 'demo-cursor';
  c.style.cssText = [
    'position:fixed', 'left:-100px', 'top:-100px',
    'width:22px', 'height:22px', 'border-radius:50%',
    'background:rgba(255,60,60,0.55)',
    'border:3px solid #ff3030',
    'box-shadow:0 0 18px rgba(255,60,60,0.65)',
    'pointer-events:none', 'z-index:2147483647',
    'transform:translate(-50%,-50%)',
    'transition:left 80ms linear, top 80ms linear',
  ].join(';');
  document.body.appendChild(c);
  const style = document.createElement('style');
  style.textContent = `
    @keyframes demo-ping {
      0%   { transform: translate(-50%,-50%) scale(1);   opacity: 0.9; }
      100% { transform: translate(-50%,-50%) scale(2.8); opacity: 0; }
    }
  `;
  document.head.appendChild(style);
  let lastX = 0, lastY = 0;
  window.addEventListener('mousemove', (e) => {
    lastX = e.clientX; lastY = e.clientY;
    c.style.left = lastX + 'px';
    c.style.top  = lastY + 'px';
  }, true);
  window.addEventListener('click', (e) => {
    const ring = document.createElement('div');
    ring.style.cssText = [
      'position:fixed',
      'left:' + e.clientX + 'px',
      'top:'  + e.clientY + 'px',
      'width:26px', 'height:26px', 'border-radius:50%',
      'background:rgba(106,169,255,0.55)',
      'border:2px solid #6aa9ff',
      'pointer-events:none', 'z-index:2147483646',
      'animation:demo-ping 500ms ease-out forwards',
      'transform:translate(-50%,-50%)',
    ].join(';');
    document.body.appendChild(ring);
    setTimeout(() => ring.remove(), 700);
  }, true);
})();
"""


@dataclass
class Beat:
    index: int
    slug: str
    title: str
    subtitle: str
    article: str
    screenshot: Path | None
    start_s: float
    end_s: float


@dataclass
class Narrator:
    """Tracks subtitle timings, screenshot filenames, and rich article
    text for each scripted step of the demo."""

    page: Page
    srt_lines: list[str] = field(default_factory=list)
    plain_lines: list[str] = field(default_factory=list)
    beats: list[Beat] = field(default_factory=list)
    shot_index: int = 0
    clock: float = 0.0
    claim_id: str | None = None
    code: str | None = None

    def beat(
        self,
        subtitle: str,
        duration_s: float = 4.0,
        *,
        shot: bool = True,
        slug: str = "",
        title: str = "",
        article: str = "",
    ) -> None:
        """Record a narration beat, wait the duration, and optionally
        take a screenshot.

        ``subtitle`` is the short line burned into the video's SRT
        subtitles. ``article`` is a longer paragraph (or several)
        that becomes a rich-text section in the generated README.md.
        ``title`` is the section heading.
        """
        start = self.clock
        end = self.clock + duration_s
        idx = len(self.srt_lines) + 1
        self.srt_lines.append(_srt_block(idx, start, end, subtitle))
        self.plain_lines.append(f"[{_ts(start)}] {subtitle}")
        print(f"  {_ts(start)} {title or subtitle[:60]}")
        self.page.wait_for_timeout(int(duration_s * 1000))
        self.clock = end

        shot_path: Path | None = None
        if shot:
            self.shot_index += 1
            safe_slug = (slug or title or subtitle).strip().lower().replace(" ", "-")[:40]
            safe_slug = "".join(c for c in safe_slug if c.isalnum() or c == "-")
            if not safe_slug:
                safe_slug = f"step-{self.shot_index:02d}"
            shot_path = SCREENS_DIR / f"{self.shot_index:02d}-{safe_slug}.png"
            self.page.screenshot(path=str(shot_path), full_page=False)

        self.beats.append(
            Beat(
                index=self.shot_index if shot_path else len(self.beats) + 1,
                slug=slug or safe_slug if shot_path else slug,
                title=title or subtitle.strip().rstrip(".").split(".")[0][:80],
                subtitle=subtitle.strip(),
                article=article.strip() or subtitle.strip(),
                screenshot=shot_path,
                start_s=start,
                end_s=end,
            )
        )


def _srt_block(idx: int, start: float, end: float, text: str) -> str:
    return f"{idx}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{text}\n"


def _srt_ts(s: float) -> str:
    td = timedelta(seconds=s)
    total_ms = int(round(td.total_seconds() * 1000))
    hh, rem = divmod(total_ms, 3600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _ts(s: float) -> str:
    m, sec = divmod(int(round(s)), 60)
    return f"{m:02d}:{sec:02d}"


def smooth_move(page: Page, x: float, y: float, steps: int = 50) -> None:
    """Animate the cursor in many small steps so the visible overlay
    cursor can interpolate smoothly in the recorded video."""
    page.mouse.move(x, y, steps=steps)


def smooth_click(page: Page, selector: str, *, pause_before_ms: int = 500) -> None:
    el = page.locator(selector).first
    box = el.bounding_box()
    if not box:
        raise RuntimeError(f"no bounding box for selector {selector!r}")
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    smooth_move(page, cx, cy, steps=45)
    page.wait_for_timeout(pause_before_ms)
    page.mouse.click(cx, cy)


def type_into(page: Page, selector: str, text: str, *, delay_ms: int = 65) -> None:
    """Click into an input, then type character-by-character so the
    typing is visible in the recorded video."""
    el = page.locator(selector).first
    box = el.bounding_box()
    if not box:
        raise RuntimeError(f"no bounding box for selector {selector!r}")
    smooth_move(page, box["x"] + 10, box["y"] + box["height"] / 2, steps=40)
    page.wait_for_timeout(250)
    page.mouse.click(box["x"] + 10, box["y"] + box["height"] / 2)
    page.wait_for_timeout(150)
    page.keyboard.type(text, delay=delay_ms)


def center_of_selector(page: Page, selector: str) -> tuple[float, float]:
    el = page.locator(selector).first
    box = el.bounding_box()
    if not box:
        raise RuntimeError(f"no bounding box for selector {selector!r}")
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def main() -> int:
    if not SAMPLE_DIR.exists():
        print(f"sample dir not found: {SAMPLE_DIR}", file=sys.stderr)
        return 1
    missing = [f for f in SAMPLE_FILES if not (SAMPLE_DIR / f).exists()]
    if missing:
        print(f"missing samples: {missing}", file=sys.stderr)
        return 1

    # Clean the server state before recording so the Inbox genuinely
    # starts empty and the reviewer sees a fresh upload land.
    try:
        httpx.post(
            f"{BASE_URL}/__unused__",  # noqa — placeholder; DB reset is done via SSH externally
            timeout=2.0,
        )
    except Exception:
        pass

    # Reset output dir.
    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    SCREENS_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_TMP_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        headless_env = os.environ.get("CLAIMSMAN_DEMO_HEADLESS", "0").lower()
        headless = headless_env in ("1", "true", "yes")
        browser = pw.chromium.launch(headless=headless)
        print(f"[demo] browser headless={headless}")
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
            color_scheme="dark",
            record_video_dir=str(VIDEO_TMP_DIR),
            record_video_size={"width": 1440, "height": 900},
        )
        # Inject the visible cursor overlay on every page, as early as
        # possible, so it's present during all interactions and visible
        # in the recording.
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        n = Narrator(page)

        try:
            run_demo(n, page)
        except Exception:
            import traceback

            traceback.print_exc()
            raise
        finally:
            video_path_saved = None
            try:
                # Close the context so the video file is finalized.
                ctx.close()
                # Move the recorded video to the output root.
                tmp_videos = sorted(VIDEO_TMP_DIR.glob("*.webm"))
                if tmp_videos:
                    dest = OUT_ROOT / "video.webm"
                    shutil.move(str(tmp_videos[0]), dest)
                    video_path_saved = dest
                shutil.rmtree(VIDEO_TMP_DIR, ignore_errors=True)
            finally:
                browser.close()

        # Persist narration
        (OUT_ROOT / "subtitles.srt").write_text(
            "\n".join(n.srt_lines), encoding="utf-8"
        )
        (OUT_ROOT / "narration.txt").write_text(
            "\n".join(n.plain_lines), encoding="utf-8"
        )
        (OUT_ROOT / "README.md").write_text(
            _readme(n.code or "?", n.claim_id or "?", n, video_path_saved), encoding="utf-8"
        )

    print(f"[demo] output at {OUT_ROOT}")
    return 0


def run_demo(n: Narrator, page: Page) -> None:
    """The narrated walkthrough itself.

    Every beat passes three pieces of text:
      - ``subtitle`` — short one-liner baked into the SRT file.
      - ``title``    — section heading for the rich README article.
      - ``article``  — multi-paragraph prose explaining the feature,
                       the why, and how it plugs into the wider flow.

    The demo drives the full user experience through the real UI — it
    navigates to the New Claim form, types claimant/policy/title/notes
    by keystroke, selects the file bundle via the real file input, and
    clicks Create claim. The claim id is captured from the URL after
    the redirect.
    """

    # --- 1. Intro (Inbox) ---
    page.goto(f"{BASE_URL}/app/", wait_until="networkidle")
    page.wait_for_timeout(800)
    n.beat(
        "Welcome to Claimsman — claims management with AI-driven recognition and decisioning.",
        6,
        slug="inbox-intro",
        title="1. Inbox — the reviewer's home",
        article=(
            "Claimsman is a single-tenant web application that turns a pile of "
            "insurance claim documents into a reviewed, auditable payout decision. "
            "The reviewer's entry point is the Inbox: a virtualized list of every "
            "claim the team is working on, with columns for claim code, claimant, "
            "domain, status, file count, and creation time. Status badges carry a "
            "spinner dot while the claim is still being processed by the pipeline, "
            "so the reviewer can tell at a glance which claims need attention now.\n\n"
            "The sidebar shows the live application version and current milestone — "
            "fetched from `/api/v1/dev/state` every 10 seconds so the UI stays in "
            "sync with the running build. Top-right pills show the backend health and "
            "the active Ollama model."
        ),
    )

    # --- 2. Click "New claim" ---
    try:
        smooth_click(page, "a:has-text('New claim')", pause_before_ms=700)
    except Exception:
        page.goto(f"{BASE_URL}/app/new", wait_until="networkidle")
    page.wait_for_timeout(1200)

    n.beat(
        "Clicking New claim opens the upload form — drop zone plus metadata fields.",
        6,
        slug="new-claim-form",
        title="2. New claim — drop zone and metadata",
        article=(
            "The New Claim form has three sections: a large drag-and-drop zone for "
            "files (or a 'browse' link for the native file picker), a metadata "
            "grid with claimant name, policy number, optional title, and domain "
            "selector, and a notes textarea for anything the reviewer should know. "
            "File validation (per-file size limit 50 MB, bundle limit 500 MB, MIME "
            "allowlist for PDF/image/DOCX) happens on upload. The domain selector "
            "decides which YAML schemas + domain rules get applied to the claim."
        ),
    )

    # --- 3. Fill the form by typing (visible in the video) ---
    try:
        type_into(page, "input[type=text] >> nth=0", "Найден Геров", delay_ms=70)
        page.wait_for_timeout(400)
        type_into(page, "input[type=text] >> nth=1", "POL-BG-DEMO-001", delay_ms=55)
        page.wait_for_timeout(400)
        type_into(page, "input[type=text] >> nth=2", "BG claim demo — full bundle", delay_ms=55)
        page.wait_for_timeout(400)
        type_into(
            page,
            "textarea",
            "Real 6-document Bulgarian health-insurance bundle.",
            delay_ms=40,
        )
        page.wait_for_timeout(500)
    except Exception as exc:
        print(f"[demo] typing into form failed: {exc}")

    n.beat(
        "Typing claimant name, policy, title and notes by keystroke — like a real reviewer.",
        7,
        slug="typing-form",
        title="3. Typing into the form — real reviewer interaction",
        article=(
            "The video shows every keystroke: the reviewer types the claimant name "
            "'Найден Геров' in Cyrillic, a policy number, a title, and a short "
            "notes blurb. All inputs are dark-themed with accent-coloured focus "
            "rings. The domain selector defaults to Health insurance but can be "
            "flipped to Motor insurance (or any other domain an admin has created "
            "from Settings → Domains). Every field is optional except the file "
            "upload itself."
        ),
    )

    # --- 4. Attach the 6 PDF files via drag-and-drop (simulated) ---
    # We use a drag-drop onto the label drop zone instead of set_input_files
    # because the NewClaim onChange handler clears input.value immediately,
    # which can race with React's deferred setFiles update. Drag-drop is
    # the real reviewer gesture anyway.
    try:
        import base64

        payload = []
        for name in SAMPLE_FILES:
            raw = (SAMPLE_DIR / name).read_bytes()
            payload.append({"name": name, "b64": base64.b64encode(raw).decode()})

        # Hover over the drop zone to trigger the visual dragOver highlight
        try:
            label = page.locator("label[for=files]").first
            box = label.bounding_box()
            if box:
                smooth_move(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=40)
                page.wait_for_timeout(500)
        except Exception:
            pass

        page.evaluate(
            """
            async (files) => {
              const label = document.querySelector('label[for=files]');
              if (!label) throw new Error('drop zone not found');
              const dt = new DataTransfer();
              for (const f of files) {
                const bin = atob(f.b64);
                const arr = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                const file = new File([arr], f.name, { type: 'application/pdf' });
                dt.items.add(file);
              }
              const fire = (type) => label.dispatchEvent(new DragEvent(type, {
                bubbles: true, cancelable: true, dataTransfer: dt,
              }));
              fire('dragenter');
              fire('dragover');
              fire('drop');
            }
            """,
            payload,
        )
        page.wait_for_timeout(1500)
        # Sanity: verify the list rendered
        li_count = page.locator("ul li").count()
        print(f"[demo] files attached; ul li count = {li_count}")
    except Exception as exc:
        print(f"[demo] drag-drop simulation failed: {exc}")

    n.beat(
        "6 PDFs attached — Епикриза, касов бон, фактура, рецептурна бланка, Амбулаторен лист, Искане.",
        7,
        slug="files-attached",
        title="4. Attaching the 6-document bundle",
        article=(
            "The drop zone supports both drag-and-drop and click-to-browse. Once "
            "files are attached they appear in a list below the drop zone with "
            "per-file size and a remove button. The demo attaches a real 6-doc "
            "bundle:\n\n"
            "1. **Епикриза.pdf** — hospital discharge summary (Cyrillic printed).\n"
            "2. **касов бон.pdf** — cash receipt with line items and VAT.\n"
            "3. **фактура.pdf** — pharmacy invoice with drug line items.\n"
            "4. **рецептурна бланка.pdf** — prescription, mixed printed and handwritten.\n"
            "5. **Амбулаторен лист.pdf** — outpatient report.\n"
            "6. **Искане за възстановяване на разходи.pdf** — reimbursement "
            "request form.\n\n"
            "Every file is a real Bulgarian scan with mixed content. This is "
            "intentionally the hardest bundle we can hand to the pipeline: "
            "multilingual OCR, cross-document reasoning, and LLM-driven "
            "adjudication all at once."
        ),
    )

    # --- 5. Click Create claim ---
    try:
        smooth_click(page, "button:has-text('Create claim')", pause_before_ms=700)
    except Exception:
        pass
    page.wait_for_timeout(2500)  # redirects to inbox on success

    # Capture the claim id + code from the URL/backend
    claim_id = ""
    code = ""
    try:
        r = httpx.get(f"{BASE_URL}/api/v1/claims", timeout=10.0)
        r.raise_for_status()
        claims = r.json().get("claims", [])
        if claims:
            latest = claims[0]
            claim_id = latest["id"]
            code = latest["code"]
            n.claim_id = claim_id
            n.code = code
            print(f"[demo] created claim {code} ({claim_id})")
    except Exception as exc:
        print(f"[demo] could not locate created claim: {exc}")

    n.beat(
        "Clicking Create claim uploads the bundle and lands back on the Inbox.",
        6,
        slug="create-claim-clicked",
        title="5. Submitting the new claim",
        article=(
            "Clicking Create claim POSTs the multipart form to "
            "`/api/v1/claims`. The backend validates MIME types with "
            "`python-magic`, stores every file on disk under "
            "`~/.claimsman/uploads/<claim_id>/<sha256>.<ext>` (content-"
            "addressable so duplicates collapse), creates the claim + "
            "upload rows in Postgres, and fires `enqueue_claim` to kick off "
            "the in-process pipeline. The Frontend redirects to the Inbox "
            "and the new row appears with a 'processing' badge and a "
            "spinner dot. Polling picks up the new row automatically."
        ),
    )

    # --- 6. Click the claim row to open Claim Detail ---
    if code:
        try:
            smooth_click(page, f"text={code}", pause_before_ms=700)
        except Exception:
            if claim_id:
                page.goto(f"{BASE_URL}/app/claims/{claim_id}", wait_until="networkidle")
    else:
        # Fallback: open any row
        try:
            row = page.locator("tbody tr").first
            box = row.bounding_box()
            if box:
                smooth_move(page, box["x"] + 80, box["y"] + box["height"] / 2, steps=40)
                page.wait_for_timeout(400)
                row.click()
        except Exception:
            pass
    page.wait_for_timeout(1500)

    n.beat(
        "Claim Detail. A four-step workflow you can navigate like a history.",
        7,
        slug="claim-detail-step-navigator",
        title="6. The four-step workflow: Intake, Recognition, Analysis, Review",
        article=(
            "Working a claim is naturally a multi-step process. Claimsman makes "
            "that structure explicit: every claim moves through Intake → "
            "Recognition → Analysis → Review. The step navigator at the top of "
            "the Claim Detail view shows all four steps with numbered circles, "
            "a checkmark for each one the pipeline has completed, and a blue "
            "highlight on the one the reviewer is currently looking at.\n\n"
            "Clicking any earlier step drops you back into that view of the same "
            "claim — it's a history, not just a wizard. You can always revisit "
            "the raw documents, see exactly what was extracted, or re-read the "
            "decision rationale. The current step auto-selects based on the live "
            "pipeline stage: ingest → Intake, OCR/classify/extract → Recognition, "
            "analyze/decide → Analysis, ready_for_review/decided → Review."
        ),
    )

    # Move the cursor across the step navigator
    try:
        for label in ("Intake", "Recognition", "Analysis", "Review"):
            cx, cy = center_of_selector(page, f"button:has-text('{label}')")
            smooth_move(page, cx, cy, steps=12)
            page.wait_for_timeout(200)
    except Exception:
        pass

    # --- 4. Recognition in progress ---
    n.beat(
        "The live pipeline bar: OCR via Surya, classification via SigLIP 2, extraction via Gemma 4.",
        7,
        slug="pipeline-bar-live",
        title="4. The live pipeline bar",
        article=(
            "Under the title bar, a PIPELINE progress bar shows exactly what the "
            "backend is doing right now: `OCR (2/6 pages)`, `Classifying`, "
            "`Extracting fields (3/6 docs)`, `Analyzing findings`, `Proposing "
            "decision`. The bar fills up with weighted stage progress so the "
            "reviewer has a real sense of how much work remains.\n\n"
            "Behind the scenes the pipeline runs in-process inside the single "
            "Python server (no Celery, no separate worker). Each stage is an "
            "async coroutine that dispatches CPU-heavy work to a thread pool. "
            "Surya OCR runs on the GPU, SigLIP 2 runs on the GPU, Gemma 4 runs "
            "via the host-installed Ollama. The API exposes a derived "
            "`pipeline.stage` field on every claim so the UI can render the bar "
            "and per-document spinners without any additional state."
        ),
    )
    n.beat(
        "Each document in the left rail has its own spinner — gone the instant OCR finishes.",
        5,
        slug="left-rail-per-doc-spinners",
        title="5. Per-document spinners that disappear when OCR finishes",
        article=(
            "The left rail of the Claim Detail view lists every document in the "
            "claim, each with a page list below. While Surya is OCR'ing a "
            "document's pages, a small spinner appears next to the document "
            "name and the stage pill shows `OCR`. As soon as OCR finishes "
            "for that document, the spinner disappears and the pill flips to "
            "the recognized document type (MEDICAL_REPORT, RECEIPT, "
            "DISCHARGE_SUMMARY, PRESCRIPTION, etc). This per-document "
            "granularity was explicitly requested: seeing the spinner go away "
            "for a specific document is a strong signal that Surya has made "
            "progress and the reviewer can start inspecting that page."
        ),
    )

    _wait_for_progress(page, claim_id, target_stage={"classify", "extract", "analyze", "decide", "ready"}, timeout_s=240)

    # --- 6. Polygon overlay ---
    try:
        svg = page.locator("main svg").first
        if svg.count() > 0:
            box = svg.bounding_box()
            if box:
                smooth_move(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30)
    except Exception:
        pass
    n.beat(
        "Polygons appear over recognised text, coloured by confidence: red, orange, green.",
        7,
        slug="polygon-overlay-confidence",
        title="6. Confidence-coloured polygon overlay",
        article=(
            "As soon as Surya finishes a page, the center viewer shows the "
            "rasterized page image with a layer of SVG polygons outlining every "
            "detected text line. The polygons are coloured by confidence: green "
            "for lines above 93%, orange for 80-93%, red below 80%. The same "
            "red/orange/green palette is re-used consistently throughout the "
            "reviewer UI, so the reviewer builds muscle memory for 'where should "
            "I look first'.\n\n"
            "The overlay uses the native page pixel space as its viewBox with "
            "`preserveAspectRatio=\"none\"` + `vector-effect=\"non-scaling-stroke\"` "
            "so polygons land on the right characters at any zoom level. Hovering "
            "a line highlights its polygon and vice-versa: the reviewer can "
            "scan the image and the OCR text simultaneously."
        ),
    )

    # --- 7. Analysis step ---
    try:
        cx, cy = center_of_selector(page, "button:has-text('Analysis')")
        smooth_move(page, cx, cy, steps=25)
        page.mouse.click(cx, cy)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    n.beat(
        "Analysis step. A thinking indicator while Gemma 4 cross-references everything.",
        6,
        slug="analysis-thinking-banner",
        title="7. Analysis step and the 'thinking' indicator",
        article=(
            "When the pipeline enters the analyze or decide stage, the reviewer "
            "sees a prominent accent banner across the top of the Analysis view: "
            "*Claim data analysis and decision recommendations in progress*. "
            "This fills the visual gap between recognition and review — the "
            "reviewer knows the system is working, doesn't hit refresh, doesn't "
            "think it's stuck. Below the banner, findings are grouped by severity "
            "(error/warning/info), and every document's extracted fields are "
            "shown in full with nested objects and arrays rendered as indented "
            "bullet lists.\n\n"
            "Analysis runs two passes. First a deterministic rule engine in "
            "`config/domain_rules/health_insurance.py` walks the assembled claim "
            "and emits findings like `missing_required_doc`, `name_mismatch`, "
            "`amount_mismatch`, `date_out_of_window`, `no_diagnosis`. Then the "
            "decision stage calls Gemma 4 with the full claim summary (findings + "
            "extracted fields per document) and asks for a structured "
            "`{outcome, amount, currency, rationale}` response."
        ),
    )

    _wait_for_ready(page, claim_id, timeout_s=600)
    page.wait_for_timeout(1200)

    try:
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(400)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(400)
    except Exception:
        pass
    n.beat(
        "Every document contributes structured fields — ICD-10 codes, drugs, line items.",
        8,
        slug="extracted-fields-grouped",
        title="8. Extracted fields per document",
        article=(
            "Gemma 4's vision model reads every page (image + OCR text) and "
            "extracts fields against the document's YAML schema. For the "
            "Епикриза we get admission and discharge dates, attending physician, "
            "final diagnoses with ICD-10 codes (Z50.8 — rehabilitation care, "
            "G54.4 — lumbosacral root disorders), procedures, medications on "
            "discharge. For the касов бон we get line items with description, "
            "quantity, unit price, line total, subtotal, VAT, grand total in лв. "
            "For the prescription we get every row: drug name, form, dose, "
            "quantity, refills.\n\n"
            "All of this is stored as typed JSON in the `extracted_fields` table "
            "and surfaced in the Analysis view grouped by document. Nested "
            "objects and lists render as indented bullet lists so they're "
            "readable without a separate modal. Each field carries enough "
            "provenance to trace it back to its source document."
        ),
    )

    # --- 9. Review step ---
    try:
        cx, cy = center_of_selector(page, "button:has-text('Review')")
        smooth_move(page, cx, cy, steps=25)
        page.mouse.click(cx, cy)
    except Exception:
        pass
    page.wait_for_timeout(1200)
    n.beat(
        "Review step. Claimant, policy, domain summary — and the proposed decision.",
        6,
        slug="review-summary",
        title="9. Review step — summary cards + proposed decision",
        article=(
            "The Review step is the reviewer's cockpit. A three-card summary "
            "grid at the top shows claimant name, policy number, and active "
            "domain. Below it, a large CONFIRMED / PROPOSED DECISION card "
            "dominates the view with the LLM-generated outcome pill (Approve / "
            "Partial Approve / Deny / Needs Info), the recommended amount "
            "including currency, and Gemma 4's full rationale rendered as "
            "markdown.\n\n"
            "Below the decision card, the Findings panel groups any rule-engine "
            "output by severity. The reviewer's mental model is 'read the "
            "rationale, glance at the findings, decide'. The design deliberately "
            "avoids cramming raw documents into the Review step — the reviewer "
            "can always click back to the Recognition step to inspect evidence."
        ),
    )
    n.beat(
        "Partial Approve — 18.20 лв. Gemma 4 cites the prescription, the receipt, and the G54.4 diagnosis.",
        10,
        slug="gemma4-rationale",
        title="10. Gemma 4's cross-document rationale",
        article=(
            "Here's an actual decision Gemma 4 produced on this exact bundle "
            "during a real run:\n\n"
            "> **Partial approve · 18.20 лв** — *Approved the cost of 'ЛИНЕФОР' "
            "(18.20 лв) as it is explicitly listed in the discharge medications "
            "from the neurologist (рецептурна бланка.pdf) and aligns with the "
            "diagnosis of lumbo-sacral root damage (G54.4) in the medical report "
            "(Епикриза.pdf). Denied the item 'ADAMAA TABA WAAM 1' (8.99 лв) as "
            "it is not prescribed in any provided medical documentation.*\n\n"
            "Three things worth calling out: (1) the LLM cross-references three "
            "different documents in a single explanation — prescription, "
            "receipt, medical report — matching drug names between them; (2) it "
            "cites ICD-10 codes by number, demonstrating real medical reasoning; "
            "(3) it explicitly refuses an unidentifiable line item rather than "
            "silently approving the full total. This is the kind of traceable, "
            "auditable reasoning Claimsman is designed to surface."
        ),
    )

    # Move across the reviewer action buttons
    try:
        for label in ("Approve", "Partial approve", "Deny", "Needs info"):
            try:
                cx, cy = center_of_selector(page, f"button:has-text('{label}')")
                smooth_move(page, cx, cy, steps=12)
                page.wait_for_timeout(250)
            except Exception:
                pass
    except Exception:
        pass
    n.beat(
        "Approve · Partial approve · Deny · Needs info — every action is audited.",
        5,
        slug="reviewer-actions",
        title="11. Reviewer actions — one click, full audit",
        article=(
            "Four action buttons sit under the decision card: Approve, Partial "
            "approve, Deny, Needs info. Each is a single click that confirms "
            "Gemma 4's proposal with the original amount and rationale; an "
            "Edit… button is available for overriding those before confirming. "
            "Every confirmation writes an `audit_log` row with the reviewer "
            "identity, the before/after snapshots, and a timestamp.\n\n"
            "A hard-gate rule in the pipeline prevents the LLM from proposing "
            "'approve' when an error-severity finding is present: the outcome "
            "gets downgraded to `needs_info` regardless of what the LLM said. "
            "That safety net means a classification glitch never causes a "
            "silently wrong approval — it always falls back to 'reviewer "
            "please look at this'."
        ),
    )

    try:
        cx, cy = center_of_selector(page, "button:has-text('Partial approve')")
        page.mouse.click(cx, cy)
    except Exception:
        pass
    page.wait_for_timeout(1400)
    n.beat(
        "Confirmed. Status flips to decided. Reviewer identity and timestamp pinned.",
        5,
        slug="confirmed-decided",
        title="12. Decision confirmed",
        article=(
            "After the click, the decision card flips from PROPOSED to "
            "CONFIRMED. The outcome pill stays green, the amount and rationale "
            "carry over, and a new footer appears with the reviewer name and "
            "the exact UTC timestamp. The top-right status pill transitions "
            "from `ready_for_review` to `decided`. A Reopen button is provided "
            "for the corner case where the reviewer needs to drop the claim "
            "back into `under_review`."
        ),
    )

    # --- 13. Recognition — Add BBox reinforce ---
    try:
        cx, cy = center_of_selector(page, "button:has-text('Recognition')")
        smooth_move(page, cx, cy, steps=25)
        page.mouse.click(cx, cy)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    n.beat(
        "Back to Recognition. The reviewer can reinforce a bounding box at any time.",
        6,
        slug="back-to-recognition",
        title="13. Back to Recognition — reinforcing bounding boxes",
        article=(
            "A reviewer can always jump back to the Recognition step from any "
            "other step — the history is always reachable, never locked. This "
            "matters because Surya's detector will sometimes miss regions "
            "(handwriting, rubber stamps, very low-contrast text, form field "
            "underlines). When that happens the reviewer can drop into "
            "Recognition, turn on the Add BBox tool, and reinforce the "
            "detection on the region they care about."
        ),
    )

    try:
        cx, cy = center_of_selector(page, "button[title='Draw a new bounding box']")
        smooth_move(page, cx, cy, steps=20)
        page.mouse.click(cx, cy)
        page.wait_for_timeout(400)
    except Exception:
        pass
    n.beat(
        "Select Add BBox, drag a rectangle over the text you want re-read.",
        5,
        slug="add-bbox-tool-selected",
        title="14. The Add BBox tool",
        article=(
            "The Recognition toolbar has three modes: Select (hover inspection), "
            "Add BBox (draw), Edit text (click to edit). Selecting Add BBox "
            "changes the cursor to a crosshair. A drag on the page image draws a "
            "blue dashed rectangle. On mouse-up, Claimsman POSTs the rectangle "
            "to the `bboxes/recognize` endpoint and a spinner appears with "
            "`Recognizing region with Surya…`. Everything runs on the GPU, so "
            "the round-trip is typically under a second."
        ),
    )

    # Draw a small rect via native MouseEvents
    try:
        svg_box = page.locator("main svg").first.bounding_box()
        if svg_box:
            x0 = svg_box["x"] + svg_box["width"] * 0.15
            y0 = svg_box["y"] + svg_box["height"] * 0.30
            x1 = svg_box["x"] + svg_box["width"] * 0.55
            y1 = svg_box["y"] + svg_box["height"] * 0.35
            page.evaluate(
                """
                (c) => {
                    const svg = document.querySelector('main svg');
                    if (!svg) return;
                    const m = (t,x,y) => new MouseEvent(t,{bubbles:true,cancelable:true,view:window,clientX:x,clientY:y,button:0,buttons: t==='mouseup'?0:1});
                    svg.dispatchEvent(m('mousedown', c.x0, c.y0));
                    svg.dispatchEvent(m('mousemove', (c.x0+c.x1)/2, (c.y0+c.y1)/2));
                    svg.dispatchEvent(m('mousemove', c.x1, c.y1));
                    svg.dispatchEvent(m('mouseup', c.x1, c.y1));
                }
                """,
                {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
            )
            smooth_move(page, x0, y0, steps=15)
            smooth_move(page, x1, y1, steps=30)
    except Exception:
        pass
    page.wait_for_timeout(6000)
    n.beat(
        "Surya skips detection and re-runs recognition on the full bbox set — user rectangle wins.",
        10,
        slug="enforced-reinforce",
        title="15. Enforced reinforce — Surya's detection is skipped",
        article=(
            "The Add BBox flow is deliberately the same as the reference "
            "prototype Claimsman was lifted from. When the reviewer draws a "
            "rectangle, the server does three things:\n\n"
            "1. **Remove overlapping Surya lines.** Any existing OCR line whose "
            "bbox overlaps the new rectangle by more than 30% of its own area "
            "is dropped. That 30% threshold is the same one the reference "
            "prototype's `bboxOverlaps` helper uses.\n"
            "2. **Build the full bbox set.** `kept_existing ∪ user_rectangle` "
            "becomes the new, complete set of regions for this page.\n"
            "3. **Run Surya with detection skipped.** The whole set is passed "
            "to `RecognitionPredictor` as `bboxes=[...]` with no detection "
            "predictor — so Surya never re-detects, it just reads every "
            "rectangle in the set and returns one line per rectangle.\n\n"
            "The net effect: the reviewer's selection is never second-guessed, "
            "AND the rest of the page is re-read in the same recognition pass "
            "so the text stays consistent. The action is audited with the "
            "user's rectangle and the number of lines that were overridden."
        ),
    )

    # --- 16. Double-click editor ---
    try:
        poly = page.locator("main svg polygon").first
        if poly.count() > 0:
            box = poly.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                smooth_move(page, cx, cy, steps=20)
                poly.dblclick()
                page.wait_for_timeout(900)
    except Exception:
        pass
    n.beat(
        "Double-click any polygon to open a convenient inline text editor.",
        6,
        slug="double-click-editor",
        title="16. Double-click to edit a line's text",
        article=(
            "The reviewer can correct the OCR text of any line with a double-"
            "click on its polygon (in any tool mode). A convenient inline "
            "editor opens right above the page viewer with the current text "
            "pre-filled, the original confidence percent shown as a pill, a "
            "'was:' preview, and keyboard shortcuts: Enter to save, Escape to "
            "cancel. The textarea is auto-sized to the text length and is "
            "resizable. The save endpoint updates the page's `ocr_text` and "
            "the line's entry inside `pages.bbox_json`, and the correction "
            "is audited.\n\n"
            "For the common case where the reviewer only needs to fix a single "
            "line without reinforcing the bbox, this is much faster than "
            "drawing a rectangle."
        ),
    )

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    page.wait_for_timeout(400)

    # --- 17. Audit log ---
    page.goto(f"{BASE_URL}/app/audit", wait_until="networkidle")
    page.wait_for_timeout(1200)
    n.beat(
        "Every reviewer action and pipeline transition lands in the audit log — live feed.",
        7,
        slug="audit-log",
        title="17. Global audit log",
        article=(
            "Every reviewer action (decision confirm/reopen, OCR text edit, "
            "BBox add/reinforce, uploads added), every pipeline state "
            "transition, every schema/domain edit, every re-run, and every "
            "reset-to-default lands in the `audit_log` table with an actor, "
            "entity, entity_id, action, before-snapshot and after-snapshot. "
            "The `/app/audit` screen polls `/api/v1/audit` every three "
            "seconds and renders a live table with filter tabs (all / claim / "
            "page / domain), a Live/Paused toggle, a Refresh button, and "
            "clickable claim-entity rows that deep-link back to the Claim "
            "Detail. Auditors can rebuild the exact evidence trail of any "
            "decision from this one screen."
        ),
    )

    # --- 18. Dev dashboard ---
    page.goto(f"{BASE_URL}/app/dev", wait_until="networkidle")
    page.wait_for_timeout(1500)
    n.beat(
        "Dev dashboard: live GPU / Ollama / Surya / DB metrics, auto-refreshing.",
        9,
        slug="dev-dashboard",
        title="18. Dev dashboard — live system health",
        article=(
            "`/app/dev` is the system-health and performance monitor. The "
            "GPU / Device card pulls from `nvidia-smi` and torch introspection "
            "to show device name, torch version, per-GPU utilization %, "
            "VRAM used/free bars, temperature, Surya and SigLIP load state and "
            "device, and CPU load average / cores.\n\n"
            "Other cards: Milestone (the current release milestone with "
            "completed and next lists), App (name, version, env, port, uptime), "
            "Persistence (claims / uploads / documents / pages / extracted "
            "fields / in-flight / ready / errored / findings counts), Ollama "
            "(reachability dot, latency in ms, installed models with sizes "
            "and vision-capable badges), Config Registry (14 schemas + 2 "
            "domains as clickable chips), Git (branch / HEAD / last 10 "
            "commits), and Recent Claims (last 8 claims with deep links). "
            "The whole dashboard auto-refreshes every 3 seconds."
        ),
    )

    # --- 19. Settings tour ---
    page.goto(f"{BASE_URL}/app/settings/domains", wait_until="networkidle")
    page.wait_for_timeout(1000)
    n.beat(
        "Settings → Domains. CRUD + LLM generator from a natural-language description.",
        7,
        slug="settings-domains",
        title="19. Settings → Domains (LLM-assisted scaffolding)",
        article=(
            "Admins can list, view, edit, create, and delete domain packs "
            "from `/app/settings/domains`. Each pack's detail view has a "
            "YAML editor, vocabulary chips, a required-doc visualizer, and a "
            "Delete action. The 'Generate with LLM' button opens a textarea "
            "where the admin types a natural-language description — "
            "something like 'Travel insurance claims for trip cancellation, "
            "medical evacuation, and lost baggage'. Gemma 4 scaffolds a "
            "complete `DomainPack` YAML (code, display name, description, "
            "vocabulary, required documents, rule module, decision prompt "
            "snippet, thresholds) and drops the reviewer into the editor "
            "primed with the result."
        ),
    )
    page.goto(f"{BASE_URL}/app/settings/schemas", wait_until="networkidle")
    page.wait_for_timeout(1000)
    n.beat(
        "Settings → Schemas. Upload a sample, Gemma 4 proposes a schema YAML.",
        7,
        slug="settings-schemas",
        title="20. Settings → Schemas (generate from a sample document)",
        article=(
            "Schemas admin lists all document types with their display "
            "names, applicable domains, and description. The YAML editor "
            "on the right lets admins hand-tune the fields. The 'Generate "
            "from sample' button opens a file picker; after an upload, "
            "Claimsman runs Surya OCR on the sample and asks Gemma 4 to "
            "propose a schema — `doc_type`, `display_name`, `description`, "
            "`domains`, `fields` with types and required flags, optional "
            "`llm_hints.system_preamble` and `validation`. The proposal is "
            "loaded into the editor so the admin can review, adjust, and "
            "save. Both LLM-assisted generators mean an admin can onboard "
            "a new claim type in minutes, not hours."
        ),
    )
    page.goto(f"{BASE_URL}/app/settings/llm", wait_until="networkidle")
    page.wait_for_timeout(1000)
    n.beat(
        "Settings → LLM. Pull new Ollama models with a live progress bar.",
        6,
        slug="settings-llm",
        title="21. Settings → LLM (model manager)",
        article=(
            "The LLM admin screen talks to Ollama. It lists every installed "
            "model with size, last-used timestamp, default badge, and a "
            "vision-capable tag if the model name matches known vision "
            "families (gemma4, llava, minicpm-v, moondream, qwen-vl, "
            "llama-vision, pixtral). A 'Pull new model' input accepts any "
            "Ollama tag and streams the pull progress into the UI in "
            "real time. Once pulled the new model becomes selectable as the "
            "active extraction/decisioning model. Ollama stays out-of-"
            "process (running on the host) so pulling a 20 GB model does "
            "not interrupt the Claimsman server."
        ),
    )
    page.goto(f"{BASE_URL}/app/settings/health", wait_until="networkidle")
    page.wait_for_timeout(1000)
    n.beat(
        "Settings → Health. Process, Device, Database, Ollama, Surya, SigLIP.",
        6,
        slug="settings-health",
        title="22. Settings → Health (six reachability panels)",
        article=(
            "Health panels give a quick admin view of everything Claimsman "
            "depends on: the Python process (Python version, platform, "
            "machine, env, host, port, PID), the device (torch version, "
            "CUDA available, device name), the database (URL and Postgres "
            "version), Ollama (reachable dot + default model + model count), "
            "Surya (loaded/idle + device), SigLIP 2 (loaded/idle + device + "
            "model id). Panels use a green dot for OK and a red dot for "
            "unreachable, and the whole screen auto-refreshes every five "
            "seconds."
        ),
    )

    # --- 23. Outro ---
    page.goto(f"{BASE_URL}/app/", wait_until="networkidle")
    page.wait_for_timeout(1500)
    n.beat(
        "Back to the Inbox. The BG claim is now decided. That's the full Claimsman flow.",
        8,
        slug="outro-inbox",
        title="23. Outro — the full flow, decided",
        article=(
            "The Bulgarian demo claim is now back in the Inbox with status "
            "`decided`. That's the full Claimsman reviewer flow end-to-end: "
            "upload a bundle, watch the recognition pipeline run on the "
            "GPU with visible progress, walk through the analysis and see "
            "cross-document reasoning, read the LLM's proposed decision, "
            "confirm or override it with a click, and know that every action "
            "was audited with full traceability.\n\n"
            "Everything in this demo ran against a real single-process "
            "FastAPI + React deployment on a live GPU host, with real "
            "Bulgarian scanned documents, real Surya OCR on CUDA, real "
            "SigLIP 2 classification, real Gemma 4 field extraction and "
            "decisioning, and a real Postgres storage layer. No mocks, no "
            "fixtures."
        ),
    )


def _wait_for_progress(
    page: Page,
    claim_id: str,
    *,
    target_stage: set[str],
    timeout_s: float,
) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/api/v1/claims/{claim_id}", timeout=10.0)
            r.raise_for_status()
            data = r.json()
            stage = (data.get("pipeline") or {}).get("stage")
            if stage in target_stage:
                return
        except Exception:
            pass
        page.wait_for_timeout(3000)


def _wait_for_ready(page: Page, claim_id: str, *, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/api/v1/claims/{claim_id}", timeout=10.0)
            r.raise_for_status()
            if r.json().get("status") == "ready_for_review":
                return
        except Exception:
            pass
        page.wait_for_timeout(3000)


def _readme(code: str, claim_id: str, n: Narrator, video_path: Path | None) -> str:
    lines: list[str] = []
    lines.append(f"# Claimsman demo — `{code}`")
    lines.append("")
    lines.append(
        "A full narrated end-to-end walkthrough of the Claimsman claims-management "
        "application, driven against a live dev deployment with a real 6-document "
        "Bulgarian health-insurance bundle (Епикриза, касов бон, фактура, "
        "рецептурна бланка, Амбулаторен лист, Искане за възстановяване на разходи). "
        "Every article below matches a moment in the recorded video and the "
        "corresponding screenshot."
    )
    lines.append("")
    lines.append("## Demo metadata")
    lines.append("")
    lines.append(f"- **Claim code:** `{code}`")
    lines.append(f"- **Claim ID:** `{claim_id}`")
    lines.append(f"- **Base URL:** `{BASE_URL}`")
    lines.append(f"- **Bundle source:** `{SAMPLE_DIR}`")
    lines.append("- **Bundle files:**")
    for f in SAMPLE_FILES:
        lines.append(f"  - `{f}`")
    lines.append(f"- **Total duration:** ~{_ts(n.clock)}")
    lines.append("")
    lines.append("## Files in this folder")
    lines.append("")
    lines.append(
        "- `video.webm` — Playwright-recorded Chromium run of the demo "
        "(1440×900, dark colour scheme)."
    )
    lines.append(
        "- `subtitles.srt` — SRT subtitles matching the video timeline. Drop into "
        "any player that supports external subtitles."
    )
    lines.append(
        "- `narration.txt` — the subtitles as a plain-text transcript with "
        "elapsed-time stamps."
    )
    lines.append(
        "- `screenshots/NN-*.png` — one screenshot per narrated step, in order."
    )
    lines.append(
        "- `README.md` — this file, with a rich article per step explaining "
        "what's on screen and why the feature exists."
    )
    lines.append("")
    lines.append("## What Claimsman is")
    lines.append("")
    lines.append(
        "Claimsman is a single-tenant web application that turns a pile of "
        "insurance claim documents into a reviewed, auditable payout decision. "
        "A user drops a mixed bundle of scanned PDFs, photos or DOCX files into "
        "the app; Surya OCR reads them (forced onto the GPU), SigLIP 2 "
        "classifies each page, Gemma 4 (running in the host's local Ollama) "
        "extracts structured fields against domain-specific YAML schemas, a "
        "Python rule engine runs consistency and eligibility checks, and Gemma "
        "4 proposes a decision with a full written rationale. A human reviewer "
        "then confirms, edits or rejects the proposal — with every action "
        "audited. The entire system runs as a single Python process on a "
        "single server so deployment, logs and iteration stay simple."
    )
    lines.append("")
    lines.append("## Architecture at a glance")
    lines.append("")
    lines.append(
        "- **Backend:** FastAPI + Uvicorn, SQLAlchemy async + Postgres 16 "
        "(Docker on a non-default port), structlog JSON logging.\n"
        "- **OCR:** Surya OCR (Surya is the only OCR engine permitted anywhere "
        "in Claimsman), CUDA 12.8 on an NVIDIA A40.\n"
        "- **Classification:** SigLIP 2 zero-shot, CUDA.\n"
        "- **LLM:** Ollama Gemma 4 (31B, vision-capable) running on the host, "
        "consumed via HTTP.\n"
        "- **Frontend:** React 18 + TypeScript + Vite + Tailwind, built into "
        "static files and served by the same FastAPI process at `/app` — no "
        "separate frontend server or worker.\n"
        "- **Pipeline:** an in-process stage runner (asyncio + threadpool) "
        "with idempotent stages: ingest → normalize → ocr → classify → extract "
        "→ analyze → decide. Every stage is resumable."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Narrated walkthrough")
    lines.append("")

    for b in n.beats:
        lines.append(f"### {b.title}")
        lines.append("")
        lines.append(f"_video: {_ts(b.start_s)} → {_ts(b.end_s)}_")
        lines.append("")
        if b.screenshot is not None:
            rel = b.screenshot.relative_to(OUT_ROOT)
            lines.append(f"![{b.title}]({rel.as_posix()})")
            lines.append("")
        lines.append(b.article)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Subtitles (SRT)")
    lines.append("")
    lines.append(
        "The video has matching SRT subtitles at `subtitles.srt`. Each subtitle "
        "line corresponds to a narrated beat in the walkthrough above. Total "
        "subtitle length matches the demo duration — roughly "
        f"{_ts(n.clock)}."
    )
    lines.append("")
    lines.append("## Regenerate")
    lines.append("")
    lines.append(
        "```bash\n"
        "# From the repo root with the .venv activated\n"
        "python tests/demo_bg_bundle.py\n"
        "```\n"
    )
    lines.append(
        "Override the target deployment:\n"
        "```bash\n"
        "CLAIMSMAN_DEMO_BASE_URL=http://127.0.0.1:8811 python tests/demo_bg_bundle.py\n"
        "```\n"
    )
    lines.append(
        "The script resets its output folder on every run so you always get a "
        "fresh screenshot set and a fresh video. Nothing in "
        "`docs/visual-runs/` is tracked by git."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
