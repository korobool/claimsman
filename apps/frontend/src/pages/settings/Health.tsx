import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";

type Panels = {
  process: Record<string, unknown>;
  device: Record<string, unknown>;
  database: Record<string, unknown>;
  ollama: Record<string, unknown>;
  surya: Record<string, unknown>;
  siglip: Record<string, unknown>;
};

export default function Health() {
  const [panels, setPanels] = useState<Panels | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const p = await api.healthPanels();
      setPanels(p);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load();
    const i = setInterval(load, 5000);
    return () => clearInterval(i);
  }, [load]);

  if (!panels && !error) return <div className="p-8 text-sm text-ink-dim">Loading…</div>;

  return (
    <div className="p-8">
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Health</h1>
        <p className="mt-1 text-sm text-ink-dim">
          Process, device, database, and ML runtime status. Auto-refreshes every 5s.
        </p>
      </header>
      {error && (
        <div className="mb-4 rounded-md border border-severity-error/40 bg-severity-error/10 px-3 py-2 text-sm text-severity-error">
          {error}
        </div>
      )}
      {panels && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Card title="Process" data={panels.process} />
          <Card title="Device" data={panels.device} />
          <Card title="Database" data={panels.database} reachableKey="reachable" />
          <Card title="Ollama" data={panels.ollama} reachableKey="reachable" />
          <Card title="Surya (OCR)" data={panels.surya} reachableKey="available" />
          <Card title="SigLIP 2 (classify)" data={panels.siglip} reachableKey="available" />
        </div>
      )}
    </div>
  );
}

function Card({
  title,
  data,
  reachableKey,
}: {
  title: string;
  data: Record<string, unknown>;
  reachableKey?: string;
}) {
  const ok = reachableKey ? Boolean(data[reachableKey]) : true;
  const dot = ok ? "bg-severity-ok" : "bg-severity-error";
  return (
    <section className="rounded-md border border-line bg-bg-raised p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-wide text-ink-faint">{title}</h2>
        {reachableKey && (
          <span className="flex items-center gap-1 text-xs text-ink-dim">
            <span className={`inline-block h-2 w-2 rounded-full ${dot}`} />
            {ok ? "ok" : "down"}
          </span>
        )}
      </div>
      <dl className="space-y-1 text-xs">
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className="flex items-start justify-between gap-3">
            <dt className="text-ink-faint">{k}</dt>
            <dd className="max-w-[70%] truncate text-right font-mono text-ink" title={String(v)}>
              {String(v ?? "—")}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
