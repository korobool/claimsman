import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AuditEntry } from "../lib/api";

const ENTITY_FILTERS = ["all", "claim", "page", "domain"] as const;
type EntityFilter = (typeof ENTITY_FILTERS)[number];

export default function Audit() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<EntityFilter>("all");
  const [live, setLive] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await api.auditEntries({
        entity: filter === "all" ? undefined : filter,
        limit: 300,
      });
      setEntries(res.entries);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [filter]);

  useEffect(() => {
    load();
    if (!live) return;
    const i = setInterval(load, 3000);
    return () => clearInterval(i);
  }, [load, live]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-line px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Audit log</h1>
          <p className="text-sm text-ink-dim">
            Every reviewer action, every pipeline state transition, every
            schema/domain edit. Live feed, auto-refresh.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <div className="flex overflow-hidden rounded-md border border-line">
            {ENTITY_FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={[
                  "px-3 py-1.5",
                  filter === f ? "bg-accent/15 text-ink" : "text-ink-dim hover:bg-bg-hover",
                ].join(" ")}
              >
                {f}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setLive((v) => !v)}
            className={[
              "rounded-md border px-3 py-1.5 font-medium",
              live
                ? "border-severity-ok/50 bg-severity-ok/10 text-severity-ok"
                : "border-line text-ink-dim hover:text-ink",
            ].join(" ")}
          >
            {live ? "Live" : "Paused"}
          </button>
          <button
            type="button"
            onClick={load}
            className="rounded-md border border-line px-3 py-1.5 text-ink-dim hover:text-ink"
          >
            Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="border-b border-severity-error/30 bg-severity-error/10 px-6 py-2 text-sm text-severity-error">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-auto px-6 py-4">
        {entries === null && <div className="text-sm text-ink-dim">Loading…</div>}
        {entries && entries.length === 0 && (
          <div className="flex h-full items-center justify-center text-center">
            <div>
              <div className="text-sm text-ink-dim">No audit events yet.</div>
              <p className="mt-1 text-xs text-ink-faint">
                Upload a claim or change a domain to generate events.
              </p>
            </div>
          </div>
        )}
        {entries && entries.length > 0 && (
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-ink-faint">
              <tr>
                <th className="pb-2 pr-3">When</th>
                <th className="pb-2 pr-3">Actor</th>
                <th className="pb-2 pr-3">Entity</th>
                <th className="pb-2 pr-3">Action</th>
                <th className="pb-2 pr-3">Details</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-t border-line/50 align-top">
                  <td className="py-2 pr-3 font-mono text-ink-faint">
                    {formatWhen(e.created_at)}
                  </td>
                  <td className="py-2 pr-3 text-ink">{e.actor}</td>
                  <td className="py-2 pr-3">
                    {e.entity === "claim" && e.entity_id ? (
                      <Link
                        to={`/claims/${e.entity_id}`}
                        className="text-accent underline-offset-2 hover:underline"
                      >
                        {e.entity}
                      </Link>
                    ) : (
                      <span className="text-ink-dim">{e.entity}</span>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <span className="rounded-full bg-bg-hover px-2 py-0.5 font-mono text-[10px] text-ink">
                      {e.action}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-ink-dim">
                    <DetailPreview value={e.after ?? e.before} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function DetailPreview({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-ink-faint">—</span>;
  if (typeof value === "string") return <span className="truncate">{value}</span>;
  const json = JSON.stringify(value);
  const short = json.length > 140 ? json.slice(0, 140) + "…" : json;
  return <span className="font-mono text-[11px]">{short}</span>;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  try {
    const t = new Date(iso);
    const delta = (Date.now() - t.getTime()) / 1000;
    if (delta < 60) return `${Math.floor(delta)}s ago`;
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
    return t.toLocaleString();
  } catch {
    return iso;
  }
}
