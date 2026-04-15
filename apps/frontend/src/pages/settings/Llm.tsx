import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

type Model = {
  name: string;
  size: number | null;
  modified_at: string | null;
  digest: string | null;
  family: string | null;
  parameter_size: string | null;
  vision: boolean;
  is_default: boolean;
};

export default function Llm() {
  const [models, setModels] = useState<Model[] | null>(null);
  const [defaultModel, setDefaultModel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pullTag, setPullTag] = useState("");
  const [pullingJob, setPullingJob] = useState<string | null>(null);
  const [pullState, setPullState] = useState<{
    status: string;
    message: string;
    completed: number;
    total: number;
  } | null>(null);
  const poller = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.llmModels();
      setModels(res.models);
      setDefaultModel(res.default_model);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!pullingJob) return;
    poller.current = setInterval(async () => {
      try {
        const s = await api.llmPullStatus(pullingJob);
        setPullState({
          status: s.status,
          message: s.message,
          completed: s.completed,
          total: s.total,
        });
        if (s.status === "done" || s.status === "error") {
          if (poller.current) clearInterval(poller.current);
          load();
          if (s.status === "error") setError(s.message);
        }
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
        if (poller.current) clearInterval(poller.current);
      }
    }, 1500);
    return () => {
      if (poller.current) clearInterval(poller.current);
    };
  }, [pullingJob, load]);

  const onPull = async () => {
    if (!pullTag.trim()) return;
    setError(null);
    setPullState(null);
    try {
      const res = await api.llmPull(pullTag.trim());
      setPullingJob(res.job_id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="p-8">
      <header className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">LLM</h1>
          <p className="mt-1 text-sm text-ink-dim">
            Local Ollama instance. Default model used for extraction and decisioning:{" "}
            <span className="font-mono text-ink">{defaultModel}</span>
          </p>
        </div>
      </header>

      <section className="mb-6 rounded-md border border-line bg-bg-raised p-4">
        <div className="mb-2 text-xs uppercase tracking-wide text-ink-faint">
          Pull a new model
        </div>
        <div className="flex gap-2">
          <input
            value={pullTag}
            onChange={(e) => setPullTag(e.target.value)}
            placeholder="e.g. llama3.2:latest, gemma4:4b"
            className="flex-1 rounded-md border border-line bg-bg-base px-3 py-2 font-mono text-sm outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={onPull}
            disabled={!pullTag || Boolean(pullingJob && pullState?.status === "running")}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-[#0b0d10] hover:bg-accent-strong disabled:opacity-50"
          >
            Pull
          </button>
        </div>
        {pullState && (
          <div className="mt-3 rounded bg-bg-base/60 p-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-mono text-ink">{pullState.status}</span>
              <span className="text-ink-dim">
                {pullState.completed && pullState.total
                  ? `${Math.round((pullState.completed / pullState.total) * 100)}%`
                  : pullState.message}
              </span>
            </div>
            {pullState.total > 0 && (
              <div className="mt-2 h-1 overflow-hidden rounded bg-bg-hover">
                <div
                  className="h-full bg-accent transition-all"
                  style={{
                    width: `${Math.min(
                      100,
                      Math.max(1, (pullState.completed / pullState.total) * 100),
                    )}%`,
                  }}
                />
              </div>
            )}
          </div>
        )}
      </section>

      {error && (
        <div className="mb-4 rounded-md border border-severity-error/40 bg-severity-error/10 px-3 py-2 text-sm text-severity-error">
          {error}
        </div>
      )}

      <section className="rounded-md border border-line">
        <div className="border-b border-line bg-bg-raised px-4 py-2 text-xs uppercase tracking-wide text-ink-faint">
          Installed models
        </div>
        {models === null && <div className="p-4 text-sm text-ink-dim">Loading…</div>}
        {models && models.length === 0 && (
          <div className="p-4 text-sm text-ink-dim">No models installed.</div>
        )}
        {models && models.length > 0 && (
          <ul className="divide-y divide-line/60">
            {models.map((m) => (
              <li key={m.name} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-ink">{m.name}</span>
                    {m.is_default && (
                      <span className="rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-semibold uppercase text-accent">
                        default
                      </span>
                    )}
                    {m.vision && (
                      <span className="rounded-full bg-severity-ok/15 px-2 py-0.5 text-[10px] font-semibold uppercase text-severity-ok">
                        vision
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-ink-faint">
                    {m.family ?? "?"} · {m.parameter_size ?? "?"}
                  </div>
                </div>
                <div className="text-xs text-ink-dim">{formatBytes(m.size)}</div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function formatBytes(size: number | null): string {
  if (!size) return "—";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  if (size < 1024 * 1024 * 1024) return `${Math.round(size / (1024 * 1024))} MB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
