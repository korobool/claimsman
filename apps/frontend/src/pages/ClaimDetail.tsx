import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type ClaimDetail, type ClaimPage } from "../lib/api";

export default function ClaimDetailPage() {
  const { claimId } = useParams<{ claimId: string }>();
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
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

  // Initial fetch + poll while the pipeline is still running.
  useEffect(() => {
    load();
    const interval = setInterval(() => {
      const c = claimRef.current;
      if (!c || c.status === "processing" || c.status === "uploaded") {
        load();
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [load]);

  // Auto-select the first page the first time the claim loads a page.
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

  if (!claim) {
    return <div className="p-8 text-sm text-ink-dim">Loading…</div>;
  }

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
        <StatusPill status={claim.status} />
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-72 shrink-0 overflow-auto border-r border-line bg-bg-raised">
          {claim.documents.length === 0 && (
            <div className="p-4 text-xs text-ink-dim">
              Pipeline has not produced pages yet. If the status pill still says
              “processing”, this panel will fill in shortly.
            </div>
          )}
          {claim.documents.map((doc) => (
            <div key={doc.id} className="border-b border-line/60 px-3 py-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="truncate text-sm font-medium" title={doc.display_name ?? ""}>
                  {doc.display_name ?? "Untitled document"}
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
                        {page.classification ? page.classification : page.text_layer_used ? "text" : "…"}
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
            {selectedPage ? <PageViewer claimId={claim.id} page={selectedPage} /> : <EmptyViewer />}
          </div>
          <aside className="w-80 shrink-0 overflow-auto border-l border-line bg-bg-raised p-5">
            <div className="mb-4">
              <div className="text-xs uppercase tracking-wide text-ink-faint">Status</div>
              <div className="mt-1"><StatusPill status={claim.status} /></div>
            </div>
            {selectedPage && (
              <div className="mb-6 rounded-md border border-line/60 bg-bg-base p-3">
                <div className="mb-2 flex items-center justify-between">
                  <div className="text-xs uppercase tracking-wide text-ink-faint">
                    Page {selectedPage.page_index + 1}
                  </div>
                  {selectedPage.classification ? (
                    <span
                      className={[
                        "rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide",
                        confidenceClass(selectedPage.confidence),
                      ].join(" ")}
                    >
                      {selectedPage.classification}
                      {selectedPage.confidence != null
                        ? ` · ${Math.round(selectedPage.confidence * 100)}%`
                        : ""}
                    </span>
                  ) : (
                    <span className="text-[10px] uppercase text-ink-faint">unclassified</span>
                  )}
                </div>
                <div className="text-[11px] text-ink-faint">
                  {selectedPage.line_count > 0
                    ? `${selectedPage.line_count} OCR lines`
                    : selectedPage.text_layer_used
                      ? "text layer only"
                      : "OCR pending"}
                </div>
                {selectedPage.ocr_preview && (
                  <div className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-snug text-ink">
                    {selectedPage.ocr_preview}
                    {selectedPage.ocr_text &&
                      selectedPage.ocr_text.length > selectedPage.ocr_preview.length && (
                        <span className="text-ink-faint"> …</span>
                      )}
                  </div>
                )}
              </div>
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
                    <span className="truncate pr-2" title={u.filename}>{u.filename}</span>
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

function PageViewer({ claimId, page }: { claimId: string; page: ClaimPage }) {
  if (!page.has_image) {
    return (
      <div className="max-w-xl rounded-lg border border-line bg-bg-raised p-6 text-sm text-ink-dim">
        <div className="mb-3 text-xs uppercase tracking-wide text-ink-faint">
          Text-only page
        </div>
        <div className="whitespace-pre-wrap font-mono text-xs text-ink">
          {page.ocr_preview ?? "(no text extracted yet)"}
        </div>
      </div>
    );
  }
  return (
    <img
      key={page.id}
      alt={`Page ${page.page_index + 1}`}
      src={`/api/v1/claims/${claimId}/pages/${page.id}/image`}
      className="max-h-full max-w-full rounded-md border border-line bg-white shadow-lg"
    />
  );
}

function EmptyViewer() {
  return (
    <div className="max-w-md text-center text-sm text-ink-dim">
      Select a page from the left rail to preview it here. Once OCR and
      classification run in later milestones, you will see bounding-box
      overlays and extracted fields in this workspace.
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
