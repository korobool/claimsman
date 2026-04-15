import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  type ClaimDetail,
  type ClaimDocument,
  type ClaimPage,
  type ExtractedField,
  type Finding,
  type OcrLine,
} from "../lib/api";

export default function ClaimDetailPage() {
  const { claimId } = useParams<{ claimId: string }>();
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [hoveredLine, setHoveredLine] = useState<number | null>(null);
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
      if (!c || c.status === "processing" || c.status === "uploaded") load();
    }, 2500);
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
      <header className="flex items-center justify-between border-b border-line px-6 py-4">
        <div>
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
        </div>
        <div className="flex items-center gap-2">
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
            <div key={doc.id} className="border-b border-line/60 px-3 py-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="truncate text-sm font-medium" title={doc.display_name ?? ""}>
                  {doc.display_name ?? "Untitled"}
                </div>
                <span className="rounded-full bg-bg-hover px-2 py-0.5 text-[10px] uppercase tracking-wide text-ink-faint">
                  {doc.doc_type}
                </span>
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
          <div className="flex min-w-0 flex-1 items-center justify-center overflow-auto bg-bg-base p-6">
            {selectedPage ? (
              <PageViewer
                claimId={claim.id}
                page={selectedPage}
                showBoxes={showBoxes}
                hoveredLine={hoveredLine}
                onHoverLine={setHoveredLine}
              />
            ) : (
              <EmptyViewer />
            )}
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
}: {
  claimId: string;
  page: ClaimPage;
  showBoxes: boolean;
  hoveredLine: number | null;
  onHoverLine: (i: number | null) => void;
}) {
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

  const w = page.width ?? 1;
  const h = page.height ?? 1;
  const lines = page.ocr_lines ?? [];

  return (
    <div className="relative inline-block max-h-full max-w-full">
      <img
        key={page.id}
        alt={`Page ${page.page_index + 1}`}
        src={`/api/v1/claims/${claimId}/pages/${page.id}/image`}
        className="block max-h-full max-w-full rounded-md border border-line bg-white shadow-lg"
      />
      {showBoxes && lines.length > 0 && (
        <svg
          className="pointer-events-none absolute inset-0 h-full w-full"
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="xMidYMid meet"
        >
          {lines.map((line, i) => {
            const points = polygonPoints(line);
            if (!points) return null;
            const color = confidenceStroke(line.confidence);
            const highlighted = hoveredLine === i;
            return (
              <polygon
                key={i}
                points={points}
                fill={highlighted ? `${color}26` : `${color}12`}
                stroke={color}
                strokeWidth={highlighted ? 3 : 1.5}
                className="pointer-events-auto cursor-crosshair"
                onMouseEnter={() => onHoverLine(i)}
                onMouseLeave={() => onHoverLine(null)}
              >
                <title>
                  {line.text} ({Math.round(line.confidence * 100)}%)
                </title>
              </polygon>
            );
          })}
        </svg>
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

function confidenceDot(confidence: number): string {
  if (confidence >= 0.93) return "bg-severity-ok";
  if (confidence >= 0.8) return "bg-severity-warn";
  return "bg-severity-error";
}
