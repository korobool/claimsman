import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Domain } from "../../lib/api";

export default function DomainDetail() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const [domain, setDomain] = useState<Domain | null>(null);
  const [yamlText, setYamlText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!code) return;
    setError(null);
    api
      .getDomain(code)
      .then((d) => {
        setDomain(d);
        setYamlText(d.yaml);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [code]);

  useEffect(() => {
    load();
  }, [load]);

  const onSave = async () => {
    if (!code) return;
    setError(null);
    setSaving(true);
    try {
      const updated = await api.updateDomainYaml(code, yamlText);
      setDomain(updated);
      setYamlText(updated.yaml);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async () => {
    if (!code) return;
    if (!confirm(`Delete domain “${code}”?`)) return;
    try {
      await api.deleteDomain(code);
      navigate("/settings/domains");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!domain) {
    return <div className="p-8 text-sm text-ink-dim">{error ?? "Loading…"}</div>;
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-line px-6 py-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-ink-faint">
            <Link to="/settings/domains" className="hover:text-ink">
              ← Domains
            </Link>
          </div>
          <h1 className="text-xl font-semibold tracking-tight">{domain.display_name}</h1>
          <p className="text-sm text-ink-dim">
            <span className="font-mono">{domain.code}</span> ·{" "}
            <span>rule module: {domain.rule_module}</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {savedAt && <span className="text-xs text-ink-faint">saved {savedAt}</span>}
          <button
            type="button"
            onClick={onDelete}
            className="rounded-md border border-line px-3 py-1.5 text-xs text-ink-dim hover:border-severity-error hover:text-severity-error"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-[#0b0d10] hover:bg-accent-strong disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </header>

      {error && (
        <div className="border-b border-severity-error/30 bg-severity-error/10 px-6 py-2 text-sm text-severity-error">
          {error}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-2 gap-4 p-6">
        <div className="flex min-h-0 flex-col">
          <div className="mb-2 text-xs uppercase tracking-wide text-ink-faint">YAML editor</div>
          <textarea
            value={yamlText}
            onChange={(e) => setYamlText(e.target.value)}
            spellCheck={false}
            className="min-h-0 flex-1 resize-none rounded-md border border-line bg-bg-raised p-4 font-mono text-xs text-ink outline-none focus:border-accent"
          />
        </div>
        <div className="flex min-h-0 flex-col gap-4 overflow-auto">
          <section className="rounded-md border border-line bg-bg-raised p-4">
            <div className="text-xs uppercase tracking-wide text-ink-faint">Description</div>
            <p className="mt-1 text-sm text-ink">{domain.description || "—"}</p>
          </section>
          <section className="rounded-md border border-line bg-bg-raised p-4">
            <div className="text-xs uppercase tracking-wide text-ink-faint">Vocabulary</div>
            <div className="mt-2 space-y-2 text-xs">
              {Object.keys(domain.vocabulary).length === 0 && (
                <div className="text-ink-faint">(empty)</div>
              )}
              {Object.entries(domain.vocabulary).map(([key, value]) => (
                <div key={key}>
                  <div className="font-medium text-ink">{key}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {Array.isArray(value) ? (
                      value.map((v, i) => (
                        <span
                          key={i}
                          className="rounded-full bg-bg-hover px-2 py-0.5 text-[11px] text-ink-dim"
                        >
                          {String(v)}
                        </span>
                      ))
                    ) : (
                      <span className="text-ink-dim">{String(value)}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
          <section className="rounded-md border border-line bg-bg-raised p-4">
            <div className="text-xs uppercase tracking-wide text-ink-faint">
              Required documents
            </div>
            {domain.required_documents.length === 0 ? (
              <div className="mt-1 text-xs text-ink-faint">(none)</div>
            ) : (
              <ul className="mt-2 space-y-1 text-xs">
                {domain.required_documents.map((group, i) => {
                  const anyOf = (group as Record<string, string[]>).any_of ?? [];
                  return (
                    <li key={i}>
                      <span className="text-ink-faint">any of: </span>
                      {anyOf.map((t) => (
                        <span
                          key={t}
                          className="ml-1 rounded-full bg-bg-hover px-2 py-0.5 text-[11px] text-ink-dim"
                        >
                          {t}
                        </span>
                      ))}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          <section className="rounded-md border border-line bg-bg-raised p-4">
            <div className="text-xs uppercase tracking-wide text-ink-faint">Thresholds</div>
            <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] text-ink">
              {JSON.stringify(domain.thresholds, null, 2)}
            </pre>
          </section>
          <section className="rounded-md border border-line bg-bg-raised p-4">
            <div className="text-xs uppercase tracking-wide text-ink-faint">
              Decision prompt snippet
            </div>
            <p className="mt-1 whitespace-pre-wrap text-xs text-ink">
              {domain.decision_prompt_snippet || "—"}
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
