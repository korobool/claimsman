import { useEffect, useState } from "react";
import { api, type HealthResponse, type SystemInfo } from "../lib/api";

export default function Inbox() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.health(), api.info()])
      .then(([h, i]) => {
        setHealth(h);
        setInfo(i);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
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
        </div>
      </header>

      <section className="flex flex-1 items-center justify-center px-6">
        <div className="max-w-xl text-center">
          <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-full bg-accent/15 text-accent">
            {/* inbox glyph */}
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
          <p className="mt-6 font-mono text-xs text-ink-faint">
            M1 skeleton is live — backend version {health?.version ?? "…"} · env {info?.env ?? "…"}
          </p>
          {error && (
            <p className="mt-3 text-xs text-severity-error">Backend unreachable: {error}</p>
          )}
        </div>
      </section>
    </div>
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
