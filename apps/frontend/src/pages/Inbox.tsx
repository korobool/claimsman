import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  api,
  type ClaimSummary,
  type HealthResponse,
  type SystemInfo,
} from "../lib/api";

export default function Inbox() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      Promise.all([api.health(), api.info(), api.listClaims()])
        .then(([h, i, c]) => {
          if (cancelled) return;
          setHealth(h);
          setInfo(i);
          setClaims(c.claims);
        })
        .catch((e: unknown) => {
          if (cancelled) return;
          setError(e instanceof Error ? e.message : String(e));
        });
    load();
    // Re-poll every 3 s so inbox badges update while pipelines run.
    const interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-line px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Inbox</h1>
          <p className="text-sm text-ink-dim">Claims waiting for your review.</p>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill label="Backend" state={error ? "error" : health ? "ok" : "loading"} />
          <StatusPill
            label={info ? `Ollama · ${info.ollama.default_model}` : "Ollama"}
            state={info ? "ok" : "loading"}
          />
          <Link
            to="/new"
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-[#0b0d10] hover:bg-accent-strong"
          >
            New claim
          </Link>
        </div>
      </header>

      <section className="flex-1 overflow-auto px-6 py-6">
        {error && (
          <div className="mb-4 rounded-md border border-severity-error/40 bg-severity-error/10 px-3 py-2 text-sm text-severity-error">
            Backend error: {error}
          </div>
        )}

        {claims === null && !error && (
          <div className="text-sm text-ink-dim">Loading claims…</div>
        )}

        {claims && claims.length === 0 && !error && <EmptyInbox />}

        {claims && claims.length > 0 && <ClaimsTable claims={claims} />}
      </section>
    </div>
  );
}

function ClaimsTable({ claims }: { claims: ClaimSummary[] }) {
  const navigate = useNavigate();
  return (
    <table className="w-full border-collapse text-sm">
      <thead className="text-left text-xs uppercase tracking-wide text-ink-faint">
        <tr>
          <th className="border-b border-line py-2 pr-4 font-medium">Code</th>
          <th className="border-b border-line py-2 pr-4 font-medium">Claimant</th>
          <th className="border-b border-line py-2 pr-4 font-medium">Domain</th>
          <th className="border-b border-line py-2 pr-4 font-medium">Status</th>
          <th className="border-b border-line py-2 pr-4 font-medium">Files</th>
          <th className="border-b border-line py-2 pr-4 font-medium">Created</th>
        </tr>
      </thead>
      <tbody>
        {claims.map((c) => (
          <tr
            key={c.id}
            onClick={() => navigate(`/claims/${c.id}`)}
            className="cursor-pointer hover:bg-bg-hover"
          >
            <td className="border-b border-line py-2 pr-4 font-mono text-xs text-ink-dim">
              {c.code}
            </td>
            <td className="border-b border-line py-2 pr-4">
              {c.claimant_name ?? <span className="text-ink-faint">—</span>}
            </td>
            <td className="border-b border-line py-2 pr-4 text-ink-dim">{c.domain}</td>
            <td className="border-b border-line py-2 pr-4">
              <StatusBadge status={c.status} />
            </td>
            <td className="border-b border-line py-2 pr-4 text-ink-dim">{c.upload_count}</td>
            <td className="border-b border-line py-2 pr-4 text-ink-dim">
              {formatDate(c.created_at)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function EmptyInbox() {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-xl text-center">
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-full bg-accent/15 text-accent">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            className="h-7 w-7"
          >
            <path d="M3 13l3-8h12l3 8v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5z" />
            <path d="M3 13h5l1 3h6l1-3h5" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold">No claims yet</h2>
        <p className="mt-2 text-sm text-ink-dim">
          Upload a claim bundle to get started. Claimsman will classify every page, extract
          structured fields against the active domain, and propose a decision you can review.
        </p>
        <Link
          to="/new"
          className="mt-6 inline-block rounded-md bg-accent px-4 py-2 text-sm font-medium text-[#0b0d10] hover:bg-accent-strong"
        >
          Create your first claim
        </Link>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const palette: Record<string, string> = {
    uploaded: "bg-accent/15 text-accent",
    processing: "bg-severity-warn/15 text-severity-warn",
    ready_for_review: "bg-severity-ok/15 text-severity-ok",
    under_review: "bg-severity-info/15 text-severity-info",
    decided: "bg-bg-hover text-ink-dim",
    error: "bg-severity-error/15 text-severity-error",
  };
  const busy = status === "processing" || status === "uploaded";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${palette[status] ?? "bg-bg-hover text-ink-dim"}`}
    >
      {busy && (
        <span
          className="inline-block h-2 w-2 animate-spin rounded-full border border-severity-warn border-t-transparent"
          role="status"
          aria-label="in progress"
        />
      )}
      {status}
    </span>
  );
}

function StatusPill({
  label,
  state,
}: {
  label: string;
  state: "ok" | "error" | "loading";
}) {
  const color =
    state === "ok"
      ? "bg-severity-ok/15 text-severity-ok"
      : state === "error"
        ? "bg-severity-error/15 text-severity-error"
        : "bg-bg-hover text-ink-dim";
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-medium ${color}`}>{label}</span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
