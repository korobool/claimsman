import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type DevState } from "../lib/api";

export default function Dev() {
  const [state, setState] = useState<DevState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ticking, setTicking] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.devState();
      setState(s);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
    if (ticking) {
      timer.current = setInterval(load, 3000);
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load, ticking]);

  if (!state && !error) {
    return <div className="p-8 text-sm text-ink-dim">Loading dev state…</div>;
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-line px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Dev state</h1>
          <p className="text-sm text-ink-dim">
            Live insight into the Claimsman build. Auto-refreshes every 3s.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setTicking((v) => !v)}
            className={[
              "rounded-md border px-3 py-1.5 text-xs font-medium",
              ticking
                ? "border-severity-ok/60 bg-severity-ok/10 text-severity-ok"
                : "border-line text-ink-dim",
            ].join(" ")}
          >
            {ticking ? "live" : "paused"}
          </button>
          <button
            type="button"
            onClick={load}
            className="rounded-md border border-line px-3 py-1.5 text-xs text-ink-dim hover:text-ink"
          >
            refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="border-b border-severity-error/30 bg-severity-error/10 px-6 py-2 text-sm text-severity-error">
          {error}
        </div>
      )}

      {state && (
        <div className="flex-1 overflow-auto p-6">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card title="Milestone" tone="accent">
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-semibold text-accent">
                  {state.milestone.id}
                </span>
                <span className="text-sm font-medium">{state.milestone.label}</span>
              </div>
              <p className="mt-3 text-xs text-ink-dim">{state.milestone.description}</p>
              <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="mb-1 uppercase tracking-wide text-ink-faint">Completed</div>
                  <ul className="space-y-0.5 text-ink">
                    {state.milestone.completed_milestones.map((m) => (
                      <li key={m}>✓ {m}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="mb-1 uppercase tracking-wide text-ink-faint">Next</div>
                  <ul className="space-y-0.5 text-ink-dim">
                    {state.milestone.next_milestones.map((m) => (
                      <li key={m}>◦ {m}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </Card>

            <Card title="App">
              <KV label="name" value={state.app.name} />
              <KV label="version" value={state.app.version} />
              <KV label="env" value={state.app.env} />
              <KV label="port" value={String(state.app.port)} />
            </Card>

            <Card title="Persistence">
              <div className="grid grid-cols-5 gap-2 text-center">
                <Stat label="claims" value={state.db.claims} />
                <Stat label="uploads" value={state.db.uploads} />
                <Stat label="documents" value={state.db.documents} />
                <Stat label="pages" value={state.db.pages} />
                <Stat label="fields" value={state.db.extracted_fields} />
              </div>
              <div className="mt-3 grid grid-cols-4 gap-2 text-center">
                <Stat label="in-flight" value={state.db.in_flight ?? 0} />
                <Stat label="ready" value={state.db.ready_for_review ?? 0} />
                <Stat label="errored" value={state.db.errored ?? 0} />
                <Stat label="findings" value={state.db.findings ?? 0} />
              </div>
            </Card>

            {state.perf && (
              <Card title="GPU / Device" span={2} tone={state.perf.cuda_available ? "accent" : undefined}>
                <div className="flex items-center gap-2 text-sm">
                  <span
                    className={[
                      "inline-block h-2 w-2 rounded-full",
                      state.perf.cuda_available ? "bg-severity-ok" : "bg-severity-warn",
                    ].join(" ")}
                  />
                  <span className="text-ink">
                    {state.perf.cuda_available ? "CUDA" : "CPU"} · {state.perf.device_name ?? "?"}
                  </span>
                  <span className="ml-auto font-mono text-xs text-ink-faint">
                    torch {state.perf.torch ?? "?"}
                  </span>
                </div>
                {state.perf.gpus && state.perf.gpus.length > 0 && (
                  <ul className="mt-3 space-y-2">
                    {state.perf.gpus.map((g) => {
                      const used_pct = (g.memory_used_mib / g.memory_total_mib) * 100;
                      return (
                        <li key={g.index} className="rounded bg-bg-base/60 p-2 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-ink">
                              GPU {g.index} · {g.name}
                            </span>
                            <span className="text-ink-faint">{g.temperature_c}°C</span>
                          </div>
                          <div className="mt-1 flex items-center justify-between text-ink-dim">
                            <span>util {g.util_percent.toFixed(0)}%</span>
                            <span>
                              vram {formatMib(g.memory_used_mib)} / {formatMib(g.memory_total_mib)}
                            </span>
                          </div>
                          <div className="mt-1 h-1 overflow-hidden rounded-full bg-bg-hover">
                            <div
                              className="h-full bg-accent"
                              style={{ width: `${used_pct}%` }}
                            />
                          </div>
                          <div className="mt-1 h-1 overflow-hidden rounded-full bg-bg-hover">
                            <div
                              className="h-full bg-severity-ok"
                              style={{ width: `${g.util_percent}%` }}
                            />
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <div className="text-ink-faint">Surya</div>
                    <div className="mt-0.5 text-ink">
                      {state.perf.surya_loaded ? "loaded" : "idle"} · {state.perf.surya_device}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-faint">SigLIP 2</div>
                    <div className="mt-0.5 text-ink">
                      {state.perf.siglip_loaded ? "loaded" : "idle"} · {state.perf.siglip_device}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-faint">CPU load avg</div>
                    <div className="mt-0.5 font-mono text-ink">
                      {state.perf.load_avg
                        ? state.perf.load_avg.map((v) => v.toFixed(2)).join(" ")
                        : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="text-ink-faint">cores</div>
                    <div className="mt-0.5 text-ink">{state.perf.cpu_count}</div>
                  </div>
                </div>
              </Card>
            )}

            <Card title="Ollama">
              <div className="flex items-center gap-2">
                <span
                  className={[
                    "inline-block h-2 w-2 rounded-full",
                    state.ollama.reachable ? "bg-severity-ok" : "bg-severity-error",
                  ].join(" ")}
                />
                <span className="text-sm">
                  {state.ollama.reachable ? "reachable" : "unreachable"}
                </span>
                {state.ollama.latency_ms != null && (
                  <span className="rounded bg-bg-hover px-1.5 py-0.5 text-[10px] text-ink-dim">
                    {state.ollama.latency_ms.toFixed(0)} ms
                  </span>
                )}
                <span className="ml-auto text-xs text-ink-faint">
                  {state.ollama.url}
                </span>
              </div>
              {state.ollama.reachable ? (
                <>
                  <div className="mt-2 text-xs text-ink-dim">
                    default: <span className="font-mono text-ink">{state.ollama.default_model}</span>
                  </div>
                  <div className="mt-1 text-xs text-ink-dim">
                    models installed: {state.ollama.model_count}
                  </div>
                  {state.ollama.models_sample && state.ollama.models_sample.length > 0 && (
                    <ul className="mt-2 space-y-0.5 text-xs text-ink-dim">
                      {state.ollama.models_sample.slice(0, 6).map((m) => (
                        <li key={m.name} className="flex items-center justify-between">
                          <span className="truncate font-mono text-ink">{m.name}</span>
                          <span className="text-ink-faint">{formatBytes(m.size)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <p className="mt-2 text-xs text-severity-error">{state.ollama.error}</p>
              )}
            </Card>

            <Card title="Config registry">
              <KV label="schemas" value={`${state.config.schemas.count}`} />
              <div className="mt-1 flex flex-wrap gap-1">
                {state.config.schemas.doc_types.map((t) => (
                  <Chip key={t}>{t}</Chip>
                ))}
              </div>
              <KV label="domains" value={`${state.config.domains.count}`} className="mt-4" />
              <div className="mt-1 flex flex-wrap gap-1">
                {state.config.domains.codes.map((c) => (
                  <Chip key={c} accent>{c}</Chip>
                ))}
              </div>
            </Card>

            <Card title="Git">
              {state.git.error ? (
                <p className="text-xs text-severity-error">{state.git.error}</p>
              ) : (
                <>
                  <KV label="branch" value={state.git.branch ?? "—"} />
                  <KV label="HEAD" value={state.git.head ?? "—"} />
                  <ul className="mt-3 space-y-1 text-[11px]">
                    {(state.git.commits ?? []).map((c) => (
                      <li key={c.sha} className="truncate">
                        <span className="font-mono text-ink-faint">{c.sha}</span>{" "}
                        <span className="text-ink">{c.subject}</span>{" "}
                        <span className="text-ink-faint">· {c.when}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Card>

            <Card title="Recent claims" span={3}>
              {state.recent_claims.length === 0 && (
                <div className="text-xs text-ink-faint">(none)</div>
              )}
              {state.recent_claims.length > 0 && (
                <table className="w-full text-xs">
                  <thead className="text-left text-[10px] uppercase tracking-wide text-ink-faint">
                    <tr>
                      <th className="pb-2 pr-3">Code</th>
                      <th className="pb-2 pr-3">Title / Claimant</th>
                      <th className="pb-2 pr-3">Domain</th>
                      <th className="pb-2 pr-3">Status</th>
                      <th className="pb-2 pr-3">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.recent_claims.map((c) => (
                      <tr key={c.id} className="border-t border-line/40">
                        <td className="py-1 pr-3 font-mono text-ink-dim">
                          <Link to={`/claims/${c.id}`} className="hover:text-ink">
                            {c.code}
                          </Link>
                        </td>
                        <td className="py-1 pr-3 text-ink">
                          {c.title ?? c.claimant_name ?? <span className="text-ink-faint">—</span>}
                        </td>
                        <td className="py-1 pr-3 text-ink-dim">{c.domain}</td>
                        <td className="py-1 pr-3">{c.status}</td>
                        <td className="py-1 pr-3 text-ink-faint">{formatWhen(c.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function Card({
  title,
  children,
  span,
  tone,
}: {
  title: string;
  children: React.ReactNode;
  span?: number;
  tone?: "accent";
}) {
  const spanClass = span ? `xl:col-span-${span}` : "";
  const accent = tone === "accent" ? "border-accent/40 bg-accent/5" : "border-line bg-bg-raised";
  return (
    <section className={`${spanClass} rounded-md border ${accent} p-4`}>
      <h2 className="mb-2 text-xs uppercase tracking-wide text-ink-faint">{title}</h2>
      {children}
    </section>
  );
}

function KV({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={`flex items-center justify-between text-xs ${className}`}>
      <span className="text-ink-faint">{label}</span>
      <span className="font-mono text-ink">{value}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-lg font-semibold text-ink">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-ink-faint">{label}</div>
    </div>
  );
}

function Chip({ children, accent }: { children: React.ReactNode; accent?: boolean }) {
  return (
    <span
      className={[
        "rounded-full px-2 py-0.5 text-[10px]",
        accent ? "bg-accent/15 text-accent" : "bg-bg-hover text-ink-dim",
      ].join(" ")}
    >
      {children}
    </span>
  );
}

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  try {
    const t = new Date(iso);
    const delta = (Date.now() - t.getTime()) / 1000;
    if (delta < 60) return "just now";
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
    return t.toLocaleDateString();
  } catch {
    return iso;
  }
}

function formatMib(mib: number): string {
  if (mib >= 1024) return `${(mib / 1024).toFixed(1)} GB`;
  return `${Math.round(mib)} MB`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${Math.round(bytes / (1024 * 1024))} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
