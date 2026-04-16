#!/usr/bin/env python3
"""Handwriting OCR recovery demo.

Uploads a single Bulgarian prescription (`рецептурна бланка.pdf`, which
has handwritten drug names and dosages) as a new claim, waits for the
pipeline to finish, then shows how a reviewer uses the Add BBox tool to
manually rectangle a handwritten line — forcing Surya to re-recognize
the enforced region. Records the full walk-through as video +
screenshots + narration, saved under
``docs/visual-runs/handwriting-demo/`` (gitignored).

The bounding box geometry is computed offline from the PDF at the
backend's render scale (``scale=2.0``, i.e. native page pixels). The
target line is ``B) Nivalin 5 mg`` in the left prescription column,
which Surya reliably misreads in its unaided detection pass.

Run:
    CLAIMSMAN_DEMO_HEADLESS=0 python tests/demo_handwriting.py
"""
from __future__ import annotations

import base64
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("CLAIMSMAN_DEMO_BASE_URL", "http://108.181.157.13:8811")

SAMPLE_DIR = Path.home() / "Downloads" / "RE_ AI доставчици"
SAMPLE_FILE = "рецептурна бланка.pdf"

OUT_ROOT = REPO_ROOT / "docs" / "visual-runs" / "handwriting-demo"
SCREENS_DIR = OUT_ROOT / "screenshots"
VIDEO_TMP_DIR = OUT_ROOT / "video-tmp"

# Target bbox in backend page-pixel space (scale=2.0 render of the PDF,
# image dimensions 1186x1644). Picked by multimodal visual inspection of
# the rendered first page: the handwritten "B) Nivalin 5 mg" drug line
# in the left prescription column. Verified by ink-density analysis:
# the run y=730..790 on the left column corresponds to that exact line.
TARGET_BBOX = (25, 715, 525, 800)
TARGET_LABEL = "B) Nivalin 5 mg"


# -------- visible-cursor injection (same as demo_bg_bundle) --------

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
  window.addEventListener('mousemove', (e) => {
    c.style.left = e.clientX + 'px';
    c.style.top  = e.clientY + 'px';
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


# ---------- narration / beat helpers ----------


@dataclass
class Beat:
    slug: str
    title: str
    subtitle: str
    article: str
    screenshot: Path | None
    start_s: float
    end_s: float


@dataclass
class Narrator:
    page: Page
    srt_lines: list[str] = field(default_factory=list)
    plain_lines: list[str] = field(default_factory=list)
    beats: list[Beat] = field(default_factory=list)
    shot_index: int = 0
    clock: float = 0.0
    claim_id: str | None = None
    code: str | None = None
    before_text: str | None = None
    after_text: str | None = None

    def beat(
        self,
        subtitle: str,
        duration_s: float = 5.0,
        *,
        shot: bool = True,
        slug: str = "",
        title: str = "",
        article: str = "",
    ) -> None:
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
                slug=slug or (safe_slug if shot_path else ""),
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


# ---------- mouse / typing helpers ----------


def smooth_move(page: Page, x: float, y: float, steps: int = 45) -> None:
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
    el = page.locator(selector).first
    box = el.bounding_box()
    if not box:
        raise RuntimeError(f"no bounding box for selector {selector!r}")
    smooth_move(page, box["x"] + 12, box["y"] + box["height"] / 2, steps=40)
    page.wait_for_timeout(250)
    page.mouse.click(box["x"] + 12, box["y"] + box["height"] / 2)
    page.wait_for_timeout(150)
    page.keyboard.type(text, delay=delay_ms)


def drop_single_file(page: Page, path: Path) -> None:
    """Simulate a drag-drop onto the New Claim drop zone."""
    b64 = base64.b64encode(path.read_bytes()).decode()
    payload = [{"name": path.name, "b64": b64}]
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
            dt.items.add(new File([arr], f.name, { type: 'application/pdf' }));
          }
          const fire = (type) => label.dispatchEvent(new DragEvent(type, {
            bubbles: true, cancelable: true, dataTransfer: dt,
          }));
          fire('dragenter'); fire('dragover'); fire('drop');
        }
        """,
        payload,
    )
    page.wait_for_timeout(1200)


# ---------- API helpers ----------


def fetch_latest_claim() -> tuple[str, str]:
    r = httpx.get(f"{BASE_URL}/api/v1/claims", timeout=10.0)
    r.raise_for_status()
    claims = r.json().get("claims", [])
    if not claims:
        return "", ""
    return claims[0]["id"], claims[0]["code"]


def fetch_claim(claim_id: str) -> dict:
    r = httpx.get(f"{BASE_URL}/api/v1/claims/{claim_id}", timeout=10.0)
    r.raise_for_status()
    return r.json()


def wait_for_ready(page: Page, claim_id: str, *, timeout_s: float = 900) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        claim = fetch_claim(claim_id)
        status = claim.get("status") or ""
        if status in ("ready_for_review", "decided", "escalated", "error"):
            return
        page.wait_for_timeout(3000)
    raise RuntimeError(f"claim {claim_id} not ready within {timeout_s}s")


def first_page(claim: dict) -> dict | None:
    for doc in claim.get("documents", []):
        for p in doc.get("pages", []):
            return p
    return None


def lines_in_region(page_data: dict, bbox: tuple[int, int, int, int]) -> list[dict]:
    """Return OCR lines whose bbox overlaps the given bbox by > 20%."""
    x0, y0, x1, y1 = bbox
    target_area = max(1, (x1 - x0) * (y1 - y0))
    out = []
    for line in (page_data or {}).get("ocr_lines") or []:
        bb = line.get("bbox") or []
        if len(bb) < 4:
            continue
        lx0, ly0, lx1, ly1 = bb[0], bb[1], bb[2], bb[3]
        ix0 = max(x0, lx0)
        iy0 = max(y0, ly0)
        ix1 = min(x1, lx1)
        iy1 = min(y1, ly1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        inter = (ix1 - ix0) * (iy1 - iy0)
        line_area = max(1, (lx1 - lx0) * (ly1 - ly0))
        if inter / line_area > 0.2 or inter / target_area > 0.2:
            out.append(line)
    return out


def summarize_lines(lines: list[dict]) -> str:
    if not lines:
        return "(no lines)"
    parts = []
    for ln in lines:
        txt = (ln.get("text") or "").strip()
        conf = ln.get("confidence", 0.0)
        parts.append(f"{txt!r} (conf={conf:.2f})")
    return " · ".join(parts)


# ---------- demo flow ----------


def main() -> int:
    src = SAMPLE_DIR / SAMPLE_FILE
    if not src.exists():
        print(f"sample not found: {src}", file=sys.stderr)
        return 1

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
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        n = Narrator(page)

        video_saved: Path | None = None
        try:
            run_demo(n, page)
        except Exception:
            import traceback
            traceback.print_exc()
            raise
        finally:
            try:
                ctx.close()
                tmp_videos = sorted(VIDEO_TMP_DIR.glob("*.webm"))
                if tmp_videos:
                    dest = OUT_ROOT / "video.webm"
                    shutil.move(str(tmp_videos[0]), dest)
                    video_saved = dest
                shutil.rmtree(VIDEO_TMP_DIR, ignore_errors=True)
            finally:
                browser.close()

        (OUT_ROOT / "subtitles.srt").write_text("\n".join(n.srt_lines), encoding="utf-8")
        (OUT_ROOT / "narration.txt").write_text("\n".join(n.plain_lines), encoding="utf-8")
        (OUT_ROOT / "README.md").write_text(_readme(n, video_saved), encoding="utf-8")

    print(f"[demo] output at {OUT_ROOT}")
    return 0


def run_demo(n: Narrator, page: Page) -> None:
    # --- 1. Inbox intro ---
    page.goto(f"{BASE_URL}/app/", wait_until="networkidle")
    page.wait_for_timeout(800)
    n.beat(
        "Handwriting is the hardest thing any OCR stack has to do.",
        6,
        slug="inbox-intro",
        title="1. Why handwriting is hard",
        article=(
            "Printed text has stable glyph shapes — every 'a' looks roughly "
            "the same. Handwriting doesn't: slant, stroke pressure, ligatures, "
            "and personal quirks break shape assumptions that printed-text "
            "models rely on. Medical prescriptions are worst of all — they "
            "mix abbreviations, doses, and drug names that don't belong to "
            "any natural-language corpus. This demo picks the hardest "
            "document in our 6-file Bulgarian bundle and shows how the "
            "reviewer recovers from imperfect OCR in a single gesture."
        ),
    )

    # --- 2. New claim form ---
    try:
        smooth_click(page, "a:has-text('New claim')", pause_before_ms=700)
    except Exception:
        page.goto(f"{BASE_URL}/app/new", wait_until="networkidle")
    page.wait_for_timeout(1200)
    n.beat(
        "We'll file a single-document claim — just the prescription.",
        5,
        slug="new-claim-form",
        title="2. New claim — single document",
        article=(
            "To keep the demo focused we only upload one file: "
            "`рецептурна бланка.pdf`. In production a claim typically bundles "
            "hospital notes, lab results, receipts and invoices — but the "
            "tooling for improving recognition on any single page is exactly "
            "the same. Everything we show here applies to every page in every "
            "claim."
        ),
    )

    # --- 3. Type metadata ---
    try:
        type_into(page, "input[type=text] >> nth=0", "Стефан Петров", delay_ms=70)
        page.wait_for_timeout(300)
        type_into(page, "input[type=text] >> nth=1", "POL-BG-RX-001", delay_ms=55)
        page.wait_for_timeout(300)
        type_into(page, "input[type=text] >> nth=2", "Handwritten prescription — bbox recovery demo", delay_ms=55)
        page.wait_for_timeout(300)
    except Exception as exc:
        print(f"[demo] typing failed: {exc}")

    n.beat(
        "Claimant, policy, title — typed character by character.",
        5,
        slug="typing",
        title="3. Claimant metadata",
        article=(
            "Real reviewers type into the form, so the demo does the same. "
            "The domain defaults to Health insurance, which loads the right "
            "schema pack for prescriptions, invoices, and receipts."
        ),
    )

    # --- 4. Drop the PDF ---
    src = SAMPLE_DIR / SAMPLE_FILE
    try:
        label = page.locator("label[for=files]").first
        box = label.bounding_box()
        if box:
            smooth_move(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=35)
            page.wait_for_timeout(400)
        drop_single_file(page, src)
        li_count = page.locator("ul li").count()
        print(f"[demo] files attached; ul li count = {li_count}")
    except Exception as exc:
        print(f"[demo] drag-drop failed: {exc}")

    n.beat(
        "The prescription is dropped onto the zone — one Bulgarian scan.",
        6,
        slug="dropped",
        title="4. Dropping the prescription",
        article=(
            "The file is a real Bulgarian pharmacy prescription form "
            "(`рецептурна бланка`). It has two handwritten columns: the left "
            "column lists three drugs (each with dosage and schedule), the "
            "right column echoes two of them in the doctor's shorthand. "
            "Handwriting is dense, cursive, and Cyrillic — a brutal OCR test."
        ),
    )

    # --- 5. Create claim ---
    try:
        smooth_click(page, "button:has-text('Create claim')", pause_before_ms=700)
    except Exception:
        pass
    page.wait_for_timeout(3000)

    claim_id, code = fetch_latest_claim()
    n.claim_id = claim_id
    n.code = code
    print(f"[demo] created claim {code} ({claim_id})")

    n.beat(
        "Claim created. Pipeline kicks off: OCR, classify, extract, analyze, decide.",
        5,
        slug="submitted",
        title="5. Submitting — the in-process pipeline",
        article=(
            "`POST /api/v1/claims` stores the file, creates the claim row, "
            "and hands the in-process pipeline a coroutine. All five stages "
            "(OCR, classification, extraction, analysis, decisioning) run "
            "inside the same Uvicorn worker that served the upload — no "
            "external queues, no second process, no RPC hops."
        ),
    )

    # --- 6. Open claim detail + wait for ready_for_review ---
    if claim_id:
        page.goto(f"{BASE_URL}/app/claims/{claim_id}", wait_until="networkidle")
    page.wait_for_timeout(1500)
    n.beat(
        "Claim Detail opens on the Intake step while recognition runs on the GPU.",
        6,
        slug="intake-waiting",
        title="6. Pipeline running",
        article=(
            "The step navigator at the top shows Intake · Recognition · "
            "Analysis · Review. While the pipeline works, the status badge "
            "carries a spinner dot. Surya OCR runs on NVIDIA A40 (CUDA) — "
            "typical per-page time is a few seconds."
        ),
    )

    wait_for_ready(page, claim_id, timeout_s=600)

    # --- 7. Recognition step ---
    try:
        smooth_click(page, "button:has-text('Recognition')", pause_before_ms=700)
    except Exception:
        pass
    page.wait_for_timeout(2000)
    n.beat(
        "Recognition — every Surya-detected line gets a polygon overlay.",
        6,
        slug="recognition",
        title="7. Recognition with polygon overlay",
        article=(
            "The prescription page is shown with a polygon drawn over every "
            "detected text line. Polygon colour encodes confidence (green = "
            "high, amber = medium, red = low). The handwritten drug block is "
            "almost entirely red — Surya isn't sure about any of it."
        ),
    )

    # --- 8. Capture BEFORE state for the target region ---
    claim = fetch_claim(claim_id)
    before_lines = lines_in_region(first_page(claim) or {}, TARGET_BBOX)
    n.before_text = summarize_lines(before_lines)
    print(f"[demo] BEFORE lines in target region: {n.before_text}")

    n.beat(
        "Zoom in: Surya read the 'Nivalin 5 mg' line as nonsense characters.",
        6,
        slug="bad-ocr",
        title="8. The imperfect read",
        article=(
            "We pick one line for the demo: the handwritten "
            f"**{TARGET_LABEL}** prescription in the left column. Before "
            "any reviewer intervention, the pipeline's stored lines for "
            f"this region were:\n\n> {n.before_text}\n\nThat text won't "
            "survive downstream drug-name extraction, so it either ends up "
            "flagged by a rule or ignored — both bad outcomes. The reviewer "
            "fixes it in a single gesture."
        ),
    )

    # --- 9. Click Add BBox tool ---
    try:
        smooth_click(page, "button:has-text('Add BBox')", pause_before_ms=700)
    except Exception as exc:
        print(f"[demo] Add BBox button missing: {exc}")
    page.wait_for_timeout(800)
    n.beat(
        "Add BBox tool engaged — next click-and-drag draws a rectangle.",
        5,
        slug="tool-selected",
        title="9. Add BBox tool",
        article=(
            "Add BBox is one of three reviewer tools alongside Inspect and "
            "Edit text. Selecting it attaches native mousedown/mousemove/"
            "mouseup listeners to the page's SVG overlay, so the reviewer "
            "can drop a rectangle anywhere on the page."
        ),
    )

    # --- 10. Compute screen coordinates for the target bbox ---
    dims = page.evaluate(
        """
        () => {
          const svg = document.querySelector('svg[viewBox]');
          if (!svg) return null;
          const r = svg.getBoundingClientRect();
          const vb = svg.viewBox.baseVal;
          return { rx: r.x, ry: r.y, rw: r.width, rh: r.height, vw: vb.width, vh: vb.height };
        }
        """
    )
    if not dims:
        raise RuntimeError("could not find SVG viewBox for bbox drawing")

    def sx(x: float) -> float:
        return dims["rx"] + x * dims["rw"] / dims["vw"]

    def sy(y: float) -> float:
        return dims["ry"] + y * dims["rh"] / dims["vh"]

    x0, y0, x1, y1 = TARGET_BBOX
    X0, Y0 = sx(x0), sy(y0)
    X1, Y1 = sx(x1), sy(y1)
    print(f"[demo] svg viewBox={dims['vw']}x{dims['vh']} rect={dims['rw']:.0f}x{dims['rh']:.0f}")
    print(f"[demo] target page-px {TARGET_BBOX} → screen ({X0:.0f},{Y0:.0f})-({X1:.0f},{Y1:.0f})")

    # --- 11. Draw the bbox over the handwritten line ---
    smooth_move(page, X0 - 60, Y0 - 60, steps=35)
    page.wait_for_timeout(400)
    smooth_move(page, X0, Y0, steps=25)
    page.wait_for_timeout(300)
    page.mouse.down()
    # Visible drag: go through a waypoint then to the far corner
    page.mouse.move((X0 + X1) / 2, (Y0 + Y1) / 2, steps=25)
    page.mouse.move(X1, Y1, steps=30)
    page.wait_for_timeout(400)
    page.mouse.up()

    n.beat(
        "Reviewer draws a rectangle around the handwritten Nivalin 5 mg line.",
        6,
        slug="draw-bbox",
        title="10. Drawing the bounding box",
        article=(
            "The dashed rectangle follows the cursor as the reviewer drags. "
            "On mouseup the front-end POSTs the bbox to `/api/v1/claims/"
            "{claim_id}/pages/{page_id}/bboxes/recognize` — the enforced "
            "re-recognition endpoint. This endpoint replaces Surya's own "
            "detection pass entirely."
        ),
    )

    # --- 12. Wait for the reinforce round-trip (Surya + backend save) ---
    page.wait_for_timeout(6000)

    # Poll the claim until the bbox_json changes (or a short timeout)
    deadline = time.time() + 25
    after_lines: list[dict] = []
    while time.time() < deadline:
        claim = fetch_claim(claim_id)
        after_lines = lines_in_region(first_page(claim) or {}, TARGET_BBOX)
        if after_lines and summarize_lines(after_lines) != n.before_text:
            break
        time.sleep(1.5)
    n.after_text = summarize_lines(after_lines)
    print(f"[demo] AFTER  lines in target region: {n.after_text}")

    n.beat(
        "Surya re-runs with detection skipped — the forced bbox is respected.",
        7,
        slug="reinforce",
        title="11. Enforced re-recognition",
        article=(
            "The backend removes any existing line that overlaps the new "
            "rectangle by more than 30%, then calls "
            "`OcrEngine.recognize_bboxes(image, [kept_existing..., new_bbox])`. "
            "Passing `bboxes=[...]` to Surya's recognition predictor skips "
            "the detection pass entirely, so the reviewer's geometry is "
            "treated as ground truth. Surya runs recognition on every bbox "
            "in order and returns one line per bbox.\n\n"
            f"**Before:** {n.before_text}\n\n**After:** {n.after_text}\n\n"
            "The 'after' line replaces the old one in the page's "
            "`bbox_json['lines']` list, the extracted-fields step picks up "
            "the corrected text on the next analysis run, and the audit log "
            "records who did it and when."
        ),
    )

    # --- 13. Audit log ---
    page.goto(f"{BASE_URL}/app/audit", wait_until="networkidle")
    page.wait_for_timeout(1500)
    n.beat(
        "The audit log shows the enforced-bbox event with timestamp and actor.",
        6,
        slug="audit",
        title="12. Audit trail",
        article=(
            "Every reviewer action writes an `AuditLog` row. For "
            "enforced-bbox recognition, the row records the claim, page, "
            "bbox coordinates, the before/after text, and the actor "
            "('reviewer' in this demo). That's the complete, defensible "
            "story behind the recovered line."
        ),
    )

    # --- 14. Back to Inbox ---
    page.goto(f"{BASE_URL}/app/", wait_until="networkidle")
    page.wait_for_timeout(1000)
    n.beat(
        "One bounding box, one improved page — demo complete.",
        5,
        slug="outro",
        title="13. Complete",
        article=(
            "A single reviewer gesture recovered an OCR line that would "
            "otherwise have been lost. No re-uploads, no retrains, no "
            "escalation — just a rectangle and an enforced re-recognition "
            "pass. Repeat as needed across any number of pages."
        ),
    )


# ---------- README generator ----------


def _readme(n: Narrator, video_path: Path | None) -> str:
    lines = ["# Claimsman handwriting recovery demo", ""]
    lines.append(f"- **Claim code:** `{n.code or '?'}`")
    lines.append(f"- **Claim ID:** `{n.claim_id or '?'}`")
    lines.append(f"- **Base URL:** `{BASE_URL}`")
    lines.append(f"- **Document:** `{SAMPLE_FILE}`")
    lines.append(f"- **Target region (page px):** `{TARGET_BBOX}`  ({TARGET_LABEL})")
    lines.append(f"- **Total duration:** ~{_ts(n.clock)}")
    lines.append("")
    lines.append("## Files in this folder")
    lines.append("")
    lines.append("- `video.webm` — Playwright Chromium recording (1440×900, dark).")
    lines.append("- `subtitles.srt` — SRT subtitles matching the video.")
    lines.append("- `narration.txt` — plain-text narration with timestamps.")
    lines.append("- `screenshots/NN-*.png` — one screenshot per beat.")
    lines.append("")
    if video_path:
        lines.append(f"Video file size: {video_path.stat().st_size // 1024} KB")
        lines.append("")
    lines.append("## Before / after")
    lines.append("")
    lines.append(f"- **Before (Surya unaided):** `{n.before_text or '(n/a)'}`")
    lines.append(f"- **After  (enforced bbox):** `{n.after_text or '(n/a)'}`")
    lines.append("")
    lines.append("## Narrated walk-through")
    lines.append("")
    for i, b in enumerate(n.beats, start=1):
        lines.append(f"### {i}. {b.title}")
        lines.append("")
        lines.append(f"_{_ts(b.start_s)} → {_ts(b.end_s)}_")
        lines.append("")
        if b.screenshot:
            rel = b.screenshot.relative_to(OUT_ROOT)
            lines.append(f"![{b.title}]({rel.as_posix()})")
            lines.append("")
        lines.append(b.article)
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "This run is driven by `tests/demo_handwriting.py`. Re-run with "
        "`CLAIMSMAN_DEMO_HEADLESS=0 python tests/demo_handwriting.py`."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
