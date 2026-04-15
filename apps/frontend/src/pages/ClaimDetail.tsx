import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  type ClaimDecision,
  type ClaimDetail,
  type ClaimDocument,
  type ClaimPage,
  type DecisionOutcome,
  type ExtractedField,
  type Finding,
  type OcrLine,
} from "../lib/api";

type ViewerTool = "select" | "add_bbox" | "edit_text";
type ClaimStep = "intake" | "recognition" | "analysis" | "review";

const STEP_ORDER: ClaimStep[] = ["intake", "recognition", "analysis", "review"];
const STEP_LABELS: Record<ClaimStep, string> = {
  intake: "Intake",
  recognition: "Recognition",
  analysis: "Analysis",
  review: "Review",
};

function defaultStepForPipeline(
  pipeline: ClaimDetail["pipeline"] | undefined,
): ClaimStep {
  if (!pipeline) return "intake";
  const s = pipeline.stage;
  if (s === "ready" || s === "decided" || s === "escalated") return "review";
  if (s === "analyze" || s === "decide") return "analysis";
  if (s === "ingest") return "intake";
  return "recognition";
}

export default function ClaimDetailPage() {
  const { claimId } = useParams<{ claimId: string }>();
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [hoveredLine, setHoveredLine] = useState<number | null>(null);
  const [tool, setTool] = useState<ViewerTool>("select");
  const [step, setStep] = useState<ClaimStep | null>(null);
  const claimRef = useRef<ClaimDetail | null>(null);
  claimRef.current = claim;

  const load = useCallback(async () => {
    if (!claimId) return;
    try {
      const c = await api.getClaim(claimId);
      setClaim(c);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [claimId]);

  useEffect(() => {
    load();
    const interval = setInterval(() => {
      const c = claimRef.current;
      if (!c || c.pipeline?.active || c.status === "processing" || c.status === "uploaded") {
        load();
      }
    }, 1500);
    return () => clearInterval(interval);
  }, [load]);

  useEffect(() => {
    if (selectedPageId || !claim) return;
    for (const doc of claim.documents) {
      if (doc.pages.length > 0) {
        setSelectedPageId(doc.pages[0].id);
        return;
      }
    }
  }, [claim, selectedPageId]);

  // Auto-advance the active step as the pipeline progresses, but only
  // if the user hasn't explicitly picked a step yet.
  useEffect(() => {
    if (step || !claim) return;
    setStep(defaultStepForPipeline(claim.pipeline));
  }, [claim, step]);

  const selectedPage = useMemo<ClaimPage | null>(() => {
    if (!claim || !selectedPageId) return null;
    for (const doc of claim.documents) {
      const hit = doc.pages.find((p) => p.id === selectedPageId);
      if (hit) return hit;
    }
    return null;
  }, [claim, selectedPageId]);

  const selectedDocument = useMemo<ClaimDocument | null>(() => {
    if (!claim || !selectedPageId) return null;
    for (const doc of claim.documents) {
      if (doc.pages.some((p) => p.id === selectedPageId)) return doc;
    }
    return null;
  }, [claim, selectedPageId]);

  if (error) {
    return (
      <div className="p-8 text-severity-error">
        {error} —{" "}
        <Link to="/" className="text-accent underline-offset-2 hover:underline">
          back to inbox
        </Link>
      </div>
    );
  }

  if (!claim) return <div className="p-8 text-sm text-ink-dim">Loading…</div>;

  const totalPages = claim.documents.reduce((sum, d) => sum + d.page_count, 0);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start justify-between border-b border-line px-6 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <Link
              to="/"
              className="text-xs uppercase tracking-wide text-ink-faint hover:text-ink"
            >
              ← Inbox
            </Link>
          </div>
          <h1 className="text-xl font-semibold tracking-tight">
            {claim.title ?? claim.claimant_name ?? claim.code}
          </h1>
          <p className="text-sm text-ink-dim">
            <span className="font-mono">{claim.code}</span> ·{" "}
            <span>{claim.domain.replace("_", " ")}</span> ·{" "}
            <span>
              {claim.documents.length} documents · {totalPages} pages
            </span>
          </p>
          {claim.pipeline?.active && <PipelineStageBar pipeline={claim.pipeline} />}
          <StepNavigator current={step ?? "intake"} pipeline={claim.pipeline} onChange={setStep} />
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-md border border-line p-0.5 text-[11px] font-medium">
            {(["select", "add_bbox", "edit_text"] as ViewerTool[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTool(t)}
                className={[
                  "rounded px-2 py-1",
                  tool === t
                    ? "bg-accent/15 text-ink"
                    : "text-ink-dim hover:bg-bg-hover hover:text-ink",
                ].join(" ")}
                aria-pressed={tool === t}
                title={
                  t === "select"
                    ? "Select tool — hover lines to inspect"
                    : t === "add_bbox"
                      ? "Draw a new bounding box"
                      : "Click a line to edit its text"
                }
              >
                {t === "select" ? "Select" : t === "add_bbox" ? "Add BBox" : "Edit text"}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setShowBoxes((v) => !v)}
            className={[
              "rounded-md border px-3 py-1.5 text-xs font-medium",
              showBoxes
                ? "border-accent/60 bg-accent/10 text-ink"
                : "border-line text-ink-dim hover:text-ink",
            ].join(" ")}
            aria-pressed={showBoxes}
          >
            {showBoxes ? "Boxes on" : "Boxes off"}
          </button>
          <AddDocsButton claimId={claim.id} onAdded={load} />
          <button
            type="button"
            onClick={async () => {
              try {
                await api.reprocessClaim(claim.id, "all");
                load();
              } catch (e: unknown) {
                setError(e instanceof Error ? e.message : String(e));
              }
            }}
            className="rounded-md border border-line px-3 py-1.5 text-xs text-ink-dim hover:text-ink"
            title="Re-run the full pipeline for this claim"
          >
            Re-run
          </button>
          <StatusPill status={claim.status} />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-72 shrink-0 overflow-auto border-r border-line bg-bg-raised">
          {claim.documents.length === 0 && (
            <div className="p-4 text-xs text-ink-dim">
              Pipeline has not produced pages yet.
            </div>
          )}
          {claim.documents.map((doc) => (
            <div key={doc.id} className="group border-b border-line/60 px-3 py-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  {doc.doc_stage === "ocr" && <Spinner size="xs" />}
                  <div className="truncate text-sm font-medium" title={doc.display_name ?? ""}>
                    {doc.display_name ?? "Untitled"}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    title="Re-run recognition (OCR + classify + extract + decide) across the full claim"
                    onClick={async () => {
                      try {
                        await api.reprocessClaim(claim.id, "ocr");
                        load();
                      } catch (e: unknown) {
                        setError(e instanceof Error ? e.message : String(e));
                      }
                    }}
                    className="hidden rounded border border-line px-1.5 py-0.5 text-[10px] text-ink-dim hover:text-ink group-hover:block"
                  >
                    re-recognize
                  </button>
                  <span className="rounded-full bg-bg-hover px-2 py-0.5 text-[10px] uppercase tracking-wide text-ink-faint">
                    {doc.doc_stage === "ready" ? doc.doc_type : doc.doc_stage}
                  </span>
                </div>
              </div>
              <ul className="space-y-1">
                {doc.pages.map((page) => (
                  <li key={page.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedPageId(page.id)}
                      aria-label={`${doc.display_name ?? "document"} page ${page.page_index + 1}`}
                      className={[
                        "flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-xs",
                        selectedPageId === page.id
                          ? "bg-accent/15 text-ink"
                          : "text-ink-dim hover:bg-bg-hover hover:text-ink",
                      ].join(" ")}
                    >
                      <span className="truncate">Page {page.page_index + 1}</span>
                      <span
                        className={[
                          "shrink-0 rounded-full px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                          confidenceClass(page.confidence),
                        ].join(" ")}
                      >
                        {page.classification ?? (page.text_layer_used ? "text" : "…")}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </aside>

        <main className="flex min-w-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col overflow-auto bg-bg-base">
            {(claim.pipeline?.stage === "analyze" || claim.pipeline?.stage === "decide") && (
              <div className="flex items-center gap-3 border-b border-accent/40 bg-accent/5 px-6 py-3">
                <Spinner />
                <div className="flex-1">
                  <div className="text-sm font-medium text-ink">
                    Claim data analysis and decision recommendations in progress
                  </div>
                  <div className="text-[11px] text-ink-dim">
                    Gemma 4 is cross-referencing findings, extracted fields, and domain
                    rules to propose an outcome.
                  </div>
                </div>
              </div>
            )}
            <div className="flex min-w-0 flex-1 items-center justify-center p-6">
              {step === "intake" && <IntakeView claim={claim} onAdded={load} />}
              {step === "recognition" && (
                selectedPage ? (
                  <PageViewer
                    claimId={claim.id}
                    page={selectedPage}
                    showBoxes={showBoxes}
                    hoveredLine={hoveredLine}
                    onHoverLine={setHoveredLine}
                    tool={tool}
                    onBBoxAdded={load}
                    onLineEdited={load}
                  />
                ) : (
                  <EmptyViewer />
                )
              )}
              {step === "analysis" && <AnalysisView claim={claim} />}
              {step === "review" && <ReviewView claim={claim} onChanged={load} />}
            </div>
          </div>
          <aside className="w-96 shrink-0 overflow-auto border-l border-line bg-bg-raised p-5">
            <div className="mb-4">
              <div className="text-xs uppercase tracking-wide text-ink-faint">Status</div>
              <div className="mt-1">
                <StatusPill status={claim.status} />
              </div>
            </div>

            {selectedPage && (
              <PageSummary page={selectedPage} onHoverLine={setHoveredLine} hoveredLine={hoveredLine} />
            )}

            {(claim.proposed_decision || claim.confirmed_decision) && (
              <DecisionCard
                claimId={claim.id}
                status={claim.status}
                proposed={claim.proposed_decision}
                confirmed={claim.confirmed_decision}
                onChanged={load}
              />
            )}

            {claim.findings && claim.findings.length > 0 && (
              <FindingsCard findings={claim.findings} summary={claim.findings_summary} />
            )}

            {selectedDocument && selectedDocument.extracted_fields.length > 0 && (
              <ExtractedFieldsCard fields={selectedDocument.extracted_fields} docType={selectedDocument.doc_type} />
            )}

            <Meta label="Claimant" value={claim.claimant_name} />
            <Meta label="Policy" value={claim.policy_number} />
            <Meta label="Domain" value={claim.domain} />
            <Meta label="Notes" value={claim.notes} multiline />
            <div className="mt-6">
              <div className="text-xs uppercase tracking-wide text-ink-faint">Uploads</div>
              <ul className="mt-2 space-y-1 text-xs text-ink-dim">
                {claim.uploads.map((u) => (
                  <li key={u.id} className="flex items-center justify-between">
                    <span className="truncate pr-2" title={u.filename}>
                      {u.filename}
                    </span>
                    <span className="text-ink-faint">{formatBytes(u.size_bytes)}</span>
                  </li>
                ))}
              </ul>
            </div>
          </aside>
        </main>
      </div>
    </div>
  );
}

function PageViewer({
  claimId,
  page,
  showBoxes,
  hoveredLine,
  onHoverLine,
  tool,
  onBBoxAdded,
  onLineEdited,
}: {
  claimId: string;
  page: ClaimPage;
  showBoxes: boolean;
  hoveredLine: number | null;
  onHoverLine: (i: number | null) => void;
  tool: ViewerTool;
  onBBoxAdded: () => void;
  onLineEdited: () => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [dragEnd, setDragEnd] = useState<{ x: number; y: number } | null>(null);
  const [recognizing, setRecognizing] = useState<
    { x0: number; y0: number; x1: number; y1: number } | null
  >(null);
  const [recognizeError, setRecognizeError] = useState<string | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editingText, setEditingText] = useState("");

  // React's synthetic events don't seem to reach the SVG reliably on
  // some Chrome + viewBox combinations (native addEventListener works
  // fine but JSX onMouseDown doesn't fire). Attach the drag listeners
  // directly to the SVG via a ref + useEffect so the behaviour mirrors
  // the reference project's vanilla-JS addEventListener approach.
  //
  // Refs hold the latest state for the event closures so the handlers
  // don't bind stale values.
  const toolRef = useRef(tool);
  toolRef.current = tool;
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const dragEndRef = useRef<{ x: number; y: number } | null>(null);
  const busyRef = useRef(false);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const toSvg = (clientX: number, clientY: number) => {
      const ctm = svg.getScreenCTM();
      if (!ctm) return { x: 0, y: 0 };
      const pt = svg.createSVGPoint();
      pt.x = clientX;
      pt.y = clientY;
      const t = pt.matrixTransform(ctm.inverse());
      return { x: t.x, y: t.y };
    };

    const down = (e: MouseEvent) => {
      if (toolRef.current !== "add_bbox") return;
      e.preventDefault();
      const p = toSvg(e.clientX, e.clientY);
      dragStartRef.current = p;
      dragEndRef.current = p;
      setDragStart(p);
      setDragEnd(p);
    };
    const move = (e: MouseEvent) => {
      if (!dragStartRef.current) return;
      const p = toSvg(e.clientX, e.clientY);
      dragEndRef.current = p;
      setDragEnd(p);
    };
    const up = async (_e: MouseEvent) => {
      if (!dragStartRef.current || !dragEndRef.current) {
        dragStartRef.current = null;
        dragEndRef.current = null;
        setDragStart(null);
        setDragEnd(null);
        return;
      }
      const s = dragStartRef.current;
      const en = dragEndRef.current;
      dragStartRef.current = null;
      dragEndRef.current = null;
      setDragStart(null);
      setDragEnd(null);

      const x0 = Math.max(0, Math.min(s.x, en.x));
      const x1 = Math.max(0, Math.max(s.x, en.x));
      const y0 = Math.max(0, Math.min(s.y, en.y));
      const y1 = Math.max(0, Math.max(s.y, en.y));
      if (x1 - x0 < 6 || y1 - y0 < 6) return;

      if (busyRef.current) return;
      busyRef.current = true;
      setRecognizing({ x0, y0, x1, y1 });
      setRecognizeError(null);
      try {
        await api.recognizeBBox(claimId, page.id, {
          bbox: [x0, y0, x1, y1],
          polygon: [
            [x0, y0],
            [x1, y0],
            [x1, y1],
            [x0, y1],
          ],
        });
        onBBoxAdded();
      } catch (err) {
        setRecognizeError(err instanceof Error ? err.message : String(err));
      } finally {
        busyRef.current = false;
        setRecognizing(null);
      }
    };
    const leave = () => {
      if (dragStartRef.current) {
        dragStartRef.current = null;
        dragEndRef.current = null;
        setDragStart(null);
        setDragEnd(null);
      }
    };

    svg.addEventListener("mousedown", down);
    svg.addEventListener("mousemove", move);
    svg.addEventListener("mouseup", up);
    svg.addEventListener("mouseleave", leave);
    return () => {
      svg.removeEventListener("mousedown", down);
      svg.removeEventListener("mousemove", move);
      svg.removeEventListener("mouseup", up);
      svg.removeEventListener("mouseleave", leave);
    };
  }, [claimId, page.id, onBBoxAdded]);

  if (!page.has_image) {
    return (
      <div className="max-w-xl rounded-lg border border-line bg-bg-raised p-6 text-sm text-ink-dim">
        <div className="mb-3 text-xs uppercase tracking-wide text-ink-faint">Text-only page</div>
        <div className="whitespace-pre-wrap font-mono text-xs text-ink">
          {page.ocr_preview ?? "(no text extracted yet)"}
        </div>
      </div>
    );
  }

  const nativeW = page.width ?? 1;
  const nativeH = page.height ?? 1;
  const lines = page.ocr_lines ?? [];

  const startEditLine = (i: number, currentText: string) => {
    if (tool !== "edit_text") return;
    setEditingIndex(i);
    setEditingText(currentText);
  };
  const commitLineEdit = async () => {
    if (editingIndex == null) return;
    try {
      await api.editOcrLine(claimId, page.id, editingIndex, editingText);
      setEditingIndex(null);
      setEditingText("");
      onLineEdited();
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  };
  const cancelLineEdit = () => {
    setEditingIndex(null);
    setEditingText("");
  };

  const cursor =
    tool === "add_bbox"
      ? "cursor-crosshair"
      : tool === "edit_text"
        ? "cursor-text"
        : "cursor-default";

  return (
    <div className="relative inline-block">
      <img
        key={page.id}
        alt={`Page ${page.page_index + 1}`}
        src={`/api/v1/claims/${claimId}/pages/${page.id}/image`}
        className="block max-h-[calc(100vh-180px)] max-w-full rounded-md border border-line bg-white shadow-lg"
        draggable={false}
      />
      <svg
        ref={svgRef}
        className={`absolute left-0 top-0 h-full w-full ${cursor}`}
        viewBox={`0 0 ${nativeW} ${nativeH}`}
        preserveAspectRatio="none"
      >
        {showBoxes &&
          lines.map((line, i) => {
            const points = polygonPoints(line);
            if (!points) return null;
            const color = confidenceStroke(line.confidence);
            const highlighted = hoveredLine === i || editingIndex === i;
            return (
              <polygon
                key={i}
                points={points}
                fill={highlighted ? `${color}44` : `${color}14`}
                stroke={color}
                strokeWidth={highlighted ? 2.2 : 1.4}
                vectorEffect="non-scaling-stroke"
                className={tool === "add_bbox" ? "pointer-events-none" : "pointer-events-auto"}
                onMouseEnter={() => onHoverLine(i)}
                onMouseLeave={() => onHoverLine(null)}
                onClick={() => startEditLine(i, line.text)}
              >
                <title>
                  {line.text} ({Math.round(line.confidence * 100)}%)
                </title>
              </polygon>
            );
          })}
        {dragStart && dragEnd && (
          <rect
            x={Math.min(dragStart.x, dragEnd.x)}
            y={Math.min(dragStart.y, dragEnd.y)}
            width={Math.abs(dragEnd.x - dragStart.x)}
            height={Math.abs(dragEnd.y - dragStart.y)}
            fill="#6aa9ff22"
            stroke="#6aa9ff"
            strokeDasharray="4 4"
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {recognizing && (
          <rect
            x={recognizing.x0}
            y={recognizing.y0}
            width={recognizing.x1 - recognizing.x0}
            height={recognizing.y1 - recognizing.y0}
            fill="#6aa9ff33"
            stroke="#6aa9ff"
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      {recognizing && (
        <div className="absolute inset-x-0 bottom-2 flex justify-center">
          <div className="flex items-center gap-2 rounded-md border border-accent/60 bg-bg-raised/95 px-3 py-2 shadow-lg">
            <Spinner />
            <span className="text-xs text-ink">Recognizing region with Surya…</span>
          </div>
        </div>
      )}

      {recognizeError && !recognizing && (
        <div className="absolute inset-x-0 bottom-2 flex justify-center">
          <div className="flex items-center gap-2 rounded-md border border-severity-error/60 bg-severity-error/10 px-3 py-2 text-xs text-severity-error shadow-lg">
            <span>Region recognize failed: {recognizeError}</span>
            <button
              type="button"
              onClick={() => setRecognizeError(null)}
              className="rounded border border-severity-error/40 px-2 py-0.5 text-[11px]"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {editingIndex != null && (
        <div className="absolute inset-x-0 bottom-2 flex justify-center">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              commitLineEdit();
            }}
            className="flex items-center gap-2 rounded-md border border-severity-warn/60 bg-bg-raised/95 px-3 py-2 shadow-lg"
          >
            <span className="text-[10px] uppercase tracking-wide text-ink-faint">
              Edit line #{editingIndex + 1}
            </span>
            <input
              autoFocus
              value={editingText}
              onChange={(e) => setEditingText(e.target.value)}
              className="w-96 rounded border border-line bg-bg-base px-2 py-1 text-xs outline-none focus:border-accent"
            />
            <button
              type="submit"
              className="rounded bg-accent px-3 py-1 text-[11px] font-medium text-[#0b0d10] hover:bg-accent-strong"
            >
              Save
            </button>
            <button
              type="button"
              onClick={cancelLineEdit}
              className="rounded border border-line px-3 py-1 text-[11px] text-ink-dim hover:text-ink"
            >
              Cancel
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

function polygonPoints(line: OcrLine): string | null {
  if (line.polygon && line.polygon.length >= 3) {
    return line.polygon.map((p) => `${p[0]},${p[1]}`).join(" ");
  }
  if (line.bbox && line.bbox.length === 4) {
    const [x0, y0, x1, y1] = line.bbox;
    return `${x0},${y0} ${x1},${y0} ${x1},${y1} ${x0},${y1}`;
  }
  return null;
}

function confidenceStroke(confidence: number): string {
  if (confidence >= 0.93) return "#3ecf8e"; // severity-ok
  if (confidence >= 0.8) return "#f1a83a"; // severity-warn
  return "#ef5a5a"; // severity-error
}

function PageSummary({
  page,
  hoveredLine,
  onHoverLine,
}: {
  page: ClaimPage;
  hoveredLine: number | null;
  onHoverLine: (i: number | null) => void;
}) {
  const lines = page.ocr_lines ?? [];
  return (
    <div className="mb-6 rounded-md border border-line/60 bg-bg-base p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-ink-faint">
          Page {page.page_index + 1}
        </div>
        {page.classification ? (
          <span
            className={[
              "rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide",
              confidenceClass(page.confidence),
            ].join(" ")}
          >
            {page.classification}
            {page.confidence != null
              ? ` · ${Math.round(page.confidence * 100)}%`
              : ""}
          </span>
        ) : (
          <span className="text-[10px] uppercase text-ink-faint">unclassified</span>
        )}
      </div>
      <div className="text-[11px] text-ink-faint">
        {page.line_count > 0
          ? `${page.line_count} OCR lines`
          : page.text_layer_used
            ? "text layer only"
            : "OCR pending"}
      </div>
      {lines.length > 0 && (
        <ul className="mt-3 max-h-56 overflow-auto font-mono text-[11px] leading-snug text-ink">
          {lines.slice(0, 60).map((line, i) => (
            <li
              key={i}
              onMouseEnter={() => onHoverLine(i)}
              onMouseLeave={() => onHoverLine(null)}
              className={[
                "flex cursor-crosshair items-start gap-2 rounded px-1",
                hoveredLine === i ? "bg-accent/10" : "",
              ].join(" ")}
            >
              <span
                className={[
                  "mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full",
                  confidenceDot(line.confidence),
                ].join(" ")}
              />
              <span className="truncate">{line.text}</span>
            </li>
          ))}
          {lines.length > 60 && (
            <li className="mt-1 text-ink-faint">… +{lines.length - 60} more</li>
          )}
        </ul>
      )}
    </div>
  );
}

function DecisionCard({
  claimId,
  status,
  proposed,
  confirmed,
  onChanged,
}: {
  claimId: string;
  status: string;
  proposed: ClaimDecision | null;
  confirmed: ClaimDecision | null;
  onChanged: () => void;
}) {
  const active = confirmed ?? proposed;
  if (!active) return null;
  const isConfirmed = Boolean(confirmed);
  const [saving, setSaving] = useState<DecisionOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showEdit, setShowEdit] = useState(false);
  const [editOutcome, setEditOutcome] = useState<DecisionOutcome>(
    active.outcome ?? "approve",
  );
  const [editAmount, setEditAmount] = useState<string>(
    active.amount != null ? String(active.amount) : "",
  );
  const [editRationale, setEditRationale] = useState<string>(
    active.rationale_md ?? "",
  );

  const submit = async (outcome: DecisionOutcome, rationale?: string, amount?: number | null) => {
    setSaving(outcome);
    setError(null);
    try {
      await api.confirmDecision(claimId, {
        outcome,
        amount: amount ?? (active.amount ?? null),
        currency: active.currency ?? null,
        rationale_md: rationale ?? active.rationale_md ?? null,
        reviewer: "reviewer",
      });
      onChanged();
      setShowEdit(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(null);
    }
  };

  const reopen = async () => {
    try {
      await api.reopenDecision(claimId);
      onChanged();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mb-6 rounded-md border border-accent/40 bg-accent/5 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-ink-faint">
          {isConfirmed ? "Confirmed decision" : "Proposed decision"}
        </div>
        <OutcomeBadge outcome={active.outcome} />
      </div>

      <div className="mb-2 flex items-baseline gap-2 text-sm">
        <span className="font-semibold text-ink">
          {active.amount != null ? formatAmount(active.amount, active.currency) : "—"}
        </span>
        {active.llm_model && (
          <span className="font-mono text-[10px] text-ink-faint">{active.llm_model}</span>
        )}
      </div>

      {active.rationale_md && (
        <div className="mb-3 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-bg-base/60 p-2 text-[11px] leading-snug text-ink">
          {active.rationale_md}
        </div>
      )}

      {error && (
        <div className="mb-2 rounded border border-severity-error/40 bg-severity-error/10 px-2 py-1 text-[11px] text-severity-error">
          {error}
        </div>
      )}

      {!isConfirmed && !showEdit && (
        <div className="flex flex-wrap gap-2 text-xs">
          <ActionButton
            label="Approve"
            tone="ok"
            disabled={saving !== null}
            loading={saving === "approve"}
            onClick={() => submit("approve")}
          />
          <ActionButton
            label="Partial approve"
            tone="warn"
            disabled={saving !== null}
            loading={saving === "partial_approve"}
            onClick={() => submit("partial_approve")}
          />
          <ActionButton
            label="Deny"
            tone="error"
            disabled={saving !== null}
            loading={saving === "deny"}
            onClick={() => submit("deny")}
          />
          <ActionButton
            label="Needs info"
            tone="info"
            disabled={saving !== null}
            loading={saving === "needs_info"}
            onClick={() => submit("needs_info")}
          />
          <button
            type="button"
            onClick={() => setShowEdit(true)}
            className="rounded-md border border-line px-3 py-1 text-xs text-ink-dim hover:text-ink"
          >
            Edit…
          </button>
        </div>
      )}

      {isConfirmed && (
        <div className="flex items-center justify-between text-[11px] text-ink-dim">
          <span>
            confirmed by <span className="text-ink">{active.confirmed_by ?? "—"}</span>
            {active.confirmed_at && <> · {new Date(active.confirmed_at).toLocaleString()}</>}
          </span>
          <button
            type="button"
            onClick={reopen}
            className="rounded-md border border-line px-3 py-1 text-[11px] text-ink-dim hover:text-ink"
          >
            Reopen
          </button>
        </div>
      )}

      {showEdit && !isConfirmed && (
        <div className="mt-2 space-y-2 rounded border border-line bg-bg-base/40 p-2 text-xs">
          <div>
            <label className="text-[10px] uppercase text-ink-faint">Outcome</label>
            <select
              value={editOutcome}
              onChange={(e) => setEditOutcome(e.target.value as DecisionOutcome)}
              className="mt-1 w-full rounded border border-line bg-bg-raised px-2 py-1"
            >
              <option value="approve">approve</option>
              <option value="partial_approve">partial_approve</option>
              <option value="deny">deny</option>
              <option value="needs_info">needs_info</option>
            </select>
          </div>
          <div>
            <label className="text-[10px] uppercase text-ink-faint">Amount</label>
            <input
              value={editAmount}
              onChange={(e) => setEditAmount(e.target.value)}
              className="mt-1 w-full rounded border border-line bg-bg-raised px-2 py-1"
            />
          </div>
          <div>
            <label className="text-[10px] uppercase text-ink-faint">Rationale</label>
            <textarea
              value={editRationale}
              onChange={(e) => setEditRationale(e.target.value)}
              rows={4}
              className="mt-1 w-full rounded border border-line bg-bg-raised px-2 py-1 font-mono text-[11px]"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowEdit(false)}
              className="rounded border border-line px-3 py-1 text-[11px] text-ink-dim hover:text-ink"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={saving !== null}
              onClick={() =>
                submit(
                  editOutcome,
                  editRationale,
                  editAmount ? Number(editAmount) : null,
                )
              }
              className="rounded bg-accent px-3 py-1 text-[11px] font-medium text-[#0b0d10] hover:bg-accent-strong disabled:opacity-50"
            >
              Save & confirm
            </button>
          </div>
        </div>
      )}

      <div className="mt-2 text-[10px] uppercase tracking-wide text-ink-faint">
        claim status: {status}
      </div>
    </div>
  );
}

function ActionButton({
  label,
  tone,
  disabled,
  loading,
  onClick,
}: {
  label: string;
  tone: "ok" | "warn" | "error" | "info";
  disabled?: boolean;
  loading?: boolean;
  onClick: () => void;
}) {
  const palette = {
    ok: "border-severity-ok/50 text-severity-ok hover:bg-severity-ok/10",
    warn: "border-severity-warn/50 text-severity-warn hover:bg-severity-warn/10",
    error: "border-severity-error/50 text-severity-error hover:bg-severity-error/10",
    info: "border-severity-info/50 text-severity-info hover:bg-severity-info/10",
  } as const;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md border px-3 py-1 font-medium disabled:opacity-40 ${palette[tone]}`}
    >
      {loading ? "…" : label}
    </button>
  );
}

function OutcomeBadge({ outcome }: { outcome: DecisionOutcome }) {
  const map: Record<DecisionOutcome, string> = {
    approve: "bg-severity-ok/15 text-severity-ok",
    partial_approve: "bg-severity-warn/15 text-severity-warn",
    deny: "bg-severity-error/15 text-severity-error",
    needs_info: "bg-severity-info/15 text-severity-info",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${map[outcome]}`}
    >
      {outcome.replace("_", " ")}
    </span>
  );
}

function formatAmount(amount: number, currency: string | null): string {
  const n = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
  return currency ? `${n} ${currency}` : n;
}

function FindingsCard({
  findings,
  summary,
}: {
  findings: Finding[];
  summary: { error: number; warning: number; info: number };
}) {
  const order: Array<Finding["severity"]> = ["error", "warning", "info"];
  return (
    <div className="mb-6 rounded-md border border-line/60 bg-bg-base p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-ink-faint">Findings</div>
        <div className="flex items-center gap-1 text-[10px] uppercase">
          {summary.error > 0 && (
            <span className="rounded-full bg-severity-error/15 px-2 py-0.5 font-semibold text-severity-error">
              {summary.error} error
            </span>
          )}
          {summary.warning > 0 && (
            <span className="rounded-full bg-severity-warn/15 px-2 py-0.5 font-semibold text-severity-warn">
              {summary.warning} warn
            </span>
          )}
          {summary.info > 0 && (
            <span className="rounded-full bg-severity-info/15 px-2 py-0.5 font-semibold text-severity-info">
              {summary.info} info
            </span>
          )}
        </div>
      </div>
      <ul className="space-y-2 text-xs">
        {order
          .flatMap((sev) => findings.filter((f) => f.severity === sev))
          .map((f) => (
            <li
              key={f.id}
              className={[
                "rounded border-l-2 px-2 py-1.5",
                f.severity === "error"
                  ? "border-severity-error bg-severity-error/5"
                  : f.severity === "warning"
                    ? "border-severity-warn bg-severity-warn/5"
                    : "border-severity-info bg-severity-info/5",
              ].join(" ")}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] uppercase text-ink-faint">
                  {f.code}
                </span>
              </div>
              <div className="mt-0.5 text-ink">{f.message}</div>
            </li>
          ))}
      </ul>
    </div>
  );
}

function ExtractedFieldsCard({
  fields,
  docType,
}: {
  fields: ExtractedField[];
  docType: string;
}) {
  return (
    <div className="mb-6 rounded-md border border-line/60 bg-bg-base p-3">
      <div className="mb-2 text-xs uppercase tracking-wide text-ink-faint">
        Extracted fields · {docType}
      </div>
      <dl className="space-y-2 text-xs">
        {fields.map((f) => (
          <div key={f.id}>
            <dt className="text-ink-faint">{f.schema_key}</dt>
            <dd className="mt-0.5 text-ink">
              <FieldValue value={f.value} />
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function FieldValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="text-ink-faint">—</span>;
  }
  if (Array.isArray(value)) {
    return (
      <ul className="ml-3 list-disc">
        {value.map((v, i) => (
          <li key={i}>
            <FieldValue value={v} />
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    return (
      <div className="ml-3 border-l border-line/60 pl-2">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k}>
            <span className="text-ink-faint">{k}: </span>
            <FieldValue value={v} />
          </div>
        ))}
      </div>
    );
  }
  return <span>{String(value)}</span>;
}

function EmptyViewer() {
  return (
    <div className="max-w-md text-center text-sm text-ink-dim">
      Select a page from the left rail.
    </div>
  );
}

function Meta({
  label,
  value,
  multiline,
}: {
  label: string;
  value: string | null | undefined;
  multiline?: boolean;
}) {
  return (
    <div className="mb-3">
      <div className="text-xs uppercase tracking-wide text-ink-faint">{label}</div>
      <div
        className={[
          "mt-0.5 text-sm",
          value ? "text-ink" : "text-ink-faint",
          multiline ? "whitespace-pre-wrap" : "truncate",
        ].join(" ")}
      >
        {value ?? "—"}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const palette: Record<string, string> = {
    uploaded: "bg-accent/15 text-accent",
    processing: "bg-severity-warn/15 text-severity-warn",
    ready_for_review: "bg-severity-ok/15 text-severity-ok",
    under_review: "bg-severity-info/15 text-severity-info",
    decided: "bg-bg-hover text-ink-dim",
    error: "bg-severity-error/15 text-severity-error",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${palette[status] ?? "bg-bg-hover text-ink-dim"}`}
    >
      {status}
    </span>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function confidenceClass(confidence: number | null | undefined): string {
  if (confidence == null) return "bg-bg-hover text-ink-dim";
  if (confidence >= 0.93) return "bg-severity-ok/15 text-severity-ok";
  if (confidence >= 0.8) return "bg-severity-warn/15 text-severity-warn";
  return "bg-severity-error/15 text-severity-error";
}

function PipelineStageBar({
  pipeline,
}: {
  pipeline: NonNullable<ClaimDetail["pipeline"]>;
}) {
  const pct = Math.max(3, Math.min(100, Math.round(pipeline.progress * 100)));
  return (
    <div className="mt-3 w-full max-w-xl">
      <div className="mb-1 flex items-center gap-2 text-[11px] text-ink-dim">
        <Spinner size="xs" />
        <span className="uppercase tracking-wide text-ink-faint">Pipeline</span>
        <span className="text-ink">{pipeline.label}</span>
        <span className="ml-auto font-mono text-ink-faint">{pct}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-bg-hover">
        <div
          className="h-full bg-accent transition-all duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function Spinner({ size = "sm" }: { size?: "xs" | "sm" }) {
  const px = size === "xs" ? "h-3 w-3 border-[1.5px]" : "h-4 w-4 border-2";
  return (
    <span
      className={`inline-block animate-spin rounded-full border-accent/60 border-t-transparent ${px}`}
      aria-label="in progress"
      role="status"
    />
  );
}

function confidenceDot(confidence: number): string {
  if (confidence >= 0.93) return "bg-severity-ok";
  if (confidence >= 0.8) return "bg-severity-warn";
  return "bg-severity-error";
}

function StepNavigator({
  current,
  pipeline,
  onChange,
}: {
  current: ClaimStep;
  pipeline?: ClaimDetail["pipeline"];
  onChange: (s: ClaimStep) => void;
}) {
  // A step is "done" when the pipeline has moved past it.
  const stage = pipeline?.stage;
  const statusOf = (step: ClaimStep): "done" | "active" | "pending" => {
    const map: Record<ClaimStep, string[]> = {
      intake: ["ingest"],
      recognition: ["ocr", "classify", "extract"],
      analysis: ["analyze", "decide"],
      review: ["ready", "decided", "escalated"],
    };
    if (step === current) return "active";
    // done if the pipeline has moved past this step
    const stepIdx = STEP_ORDER.indexOf(step);
    const currentIdx = STEP_ORDER.indexOf(current);
    if (stepIdx < currentIdx) return "done";
    if (stage && map[step].includes(stage)) return "active";
    return "pending";
  };
  return (
    <div className="mt-4 flex items-center gap-0 text-[11px]">
      {STEP_ORDER.map((s, i) => {
        const status = statusOf(s);
        const isLast = i === STEP_ORDER.length - 1;
        const dotClass =
          status === "done"
            ? "bg-severity-ok text-[#0b0d10]"
            : status === "active"
              ? "bg-accent text-[#0b0d10]"
              : "bg-bg-hover text-ink-faint";
        const labelClass =
          status === "pending" ? "text-ink-faint" : "text-ink";
        return (
          <div key={s} className="flex items-center">
            <button
              type="button"
              onClick={() => onChange(s)}
              className="group flex items-center gap-2"
              aria-current={status === "active" ? "step" : undefined}
            >
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold ${dotClass}`}
              >
                {status === "done" ? "✓" : i + 1}
              </span>
              <span className={`font-medium ${labelClass}`}>{STEP_LABELS[s]}</span>
            </button>
            {!isLast && (
              <span
                className={`mx-3 h-px w-8 ${
                  status === "done" ? "bg-severity-ok" : "bg-line"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function IntakeView({
  claim,
  onAdded,
}: {
  claim: ClaimDetail;
  onAdded: () => void;
}) {
  return (
    <div className="mx-auto w-full max-w-3xl">
      <h2 className="text-lg font-semibold tracking-tight">Intake</h2>
      <p className="mt-1 text-sm text-ink-dim">
        Files in this claim bundle. You can add more documents and the
        pipeline will re-run analysis incrementally.
      </p>
      <div className="mt-6 rounded-md border border-line bg-bg-raised">
        <div className="border-b border-line/60 px-4 py-2 text-xs uppercase tracking-wide text-ink-faint">
          Uploads ({claim.uploads.length})
        </div>
        <ul className="divide-y divide-line/60">
          {claim.uploads.map((u) => (
            <li key={u.id} className="flex items-center justify-between px-4 py-2 text-sm">
              <span className="truncate">{u.filename}</span>
              <span className="shrink-0 text-xs text-ink-faint">
                {u.mime_type} · {formatBytes(u.size_bytes)}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-6 flex items-center justify-between rounded-md border border-dashed border-line bg-bg-raised px-4 py-6 text-sm">
        <div>
          <div className="font-medium">Need to add more documents?</div>
          <div className="text-xs text-ink-dim">
            Appending files re-runs the pipeline on the full (old + new) evidence.
          </div>
        </div>
        <AddDocsButton claimId={claim.id} onAdded={onAdded} />
      </div>
    </div>
  );
}

function AnalysisView({ claim }: { claim: ClaimDetail }) {
  const thinking =
    claim.pipeline?.stage === "analyze" || claim.pipeline?.stage === "decide";
  const allFields = claim.documents.flatMap((d) =>
    d.extracted_fields.map((ef) => ({ doc: d, field: ef })),
  );
  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <h2 className="text-lg font-semibold tracking-tight">Analysis</h2>
      {thinking && (
        <div className="flex items-start gap-3 rounded-md border border-accent/40 bg-accent/5 p-4">
          <Spinner />
          <div>
            <div className="text-sm font-medium text-ink">
              Claim data analysis and decision recommendations in progress
            </div>
            <div className="mt-1 text-xs text-ink-dim">
              Gemma 4 is cross-referencing findings, extracted fields, and domain
              rules to propose an outcome.
            </div>
          </div>
        </div>
      )}
      {claim.findings && claim.findings.length > 0 ? (
        <FindingsCard findings={claim.findings} summary={claim.findings_summary} />
      ) : (
        <div className="rounded-md border border-line bg-bg-raised p-4 text-sm text-ink-dim">
          No findings have been generated yet.
        </div>
      )}
      {claim.documents.map((doc) => (
        doc.extracted_fields.length > 0 && (
          <div key={doc.id}>
            <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-wide text-ink-faint">
              <span>{doc.display_name ?? doc.doc_type}</span>
              <span>{doc.doc_type}</span>
            </div>
            <ExtractedFieldsCard fields={doc.extracted_fields} docType={doc.doc_type} />
          </div>
        )
      ))}
      {allFields.length === 0 && !thinking && (
        <div className="rounded-md border border-line bg-bg-raised p-4 text-sm text-ink-dim">
          No extracted fields yet.
        </div>
      )}
    </div>
  );
}

function ReviewView({
  claim,
  onChanged,
}: {
  claim: ClaimDetail;
  onChanged: () => void;
}) {
  if (!claim.proposed_decision && !claim.confirmed_decision) {
    return (
      <div className="mx-auto max-w-xl text-center text-sm text-ink-dim">
        <h2 className="mb-2 text-lg font-semibold text-ink">Review</h2>
        <p>
          The pipeline has not produced a decision yet. Switch to Recognition
          or Analysis to watch progress, or wait for the decision to appear here.
        </p>
      </div>
    );
  }
  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <h2 className="text-lg font-semibold tracking-tight">Review</h2>
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div className="rounded-md border border-line bg-bg-raised p-3">
          <div className="text-xs uppercase text-ink-faint">Claimant</div>
          <div className="mt-1 text-ink">{claim.claimant_name ?? "—"}</div>
        </div>
        <div className="rounded-md border border-line bg-bg-raised p-3">
          <div className="text-xs uppercase text-ink-faint">Policy</div>
          <div className="mt-1 text-ink">{claim.policy_number ?? "—"}</div>
        </div>
        <div className="rounded-md border border-line bg-bg-raised p-3">
          <div className="text-xs uppercase text-ink-faint">Domain</div>
          <div className="mt-1 text-ink">{claim.domain}</div>
        </div>
      </div>
      <DecisionCard
        claimId={claim.id}
        status={claim.status}
        proposed={claim.proposed_decision}
        confirmed={claim.confirmed_decision}
        onChanged={onChanged}
      />
      {claim.findings && claim.findings.length > 0 && (
        <FindingsCard findings={claim.findings} summary={claim.findings_summary} />
      )}
      {claim.notes && (
        <div className="rounded-md border border-line bg-bg-raised p-4 text-sm">
          <div className="text-xs uppercase text-ink-faint">Reviewer notes</div>
          <div className="mt-1 whitespace-pre-wrap text-ink">{claim.notes}</div>
        </div>
      )}
    </div>
  );
}

function AddDocsButton({
  claimId,
  onAdded,
}: {
  claimId: string;
  onAdded: () => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (files.length === 0) return;
    setBusy(true);
    try {
      await api.addUploadsToClaim(claimId, files);
      onAdded();
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept="image/*,application/pdf,.docx"
        className="hidden"
        onChange={onPick}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="rounded-md border border-line px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
        title="Add more documents to this claim and re-run analysis"
      >
        {busy ? "Uploading…" : "Add documents"}
      </button>
    </>
  );
}
