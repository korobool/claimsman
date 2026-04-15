import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Domain } from "../../lib/api";

const NEW_DOMAIN_YAML = `code: my_domain
display_name: My domain
description: >
  Describe the domain in a sentence or two.
vocabulary: {}
required_documents: []
rule_module: my_domain
decision_prompt_snippet: ''
thresholds:
  low_confidence: 0.80
  amount_tolerance: 0.02
`;

export default function DomainsList() {
  const [domains, setDomains] = useState<Domain[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genDescription, setGenDescription] = useState("");
  const [genBusy, setGenBusy] = useState(false);
  const navigate = useNavigate();

  const load = useCallback(() => {
    setError(null);
    api
      .listDomains()
      .then((r) => setDomains(r.domains))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onCreate = async () => {
    setError(null);
    if (!/^[a-z][a-z0-9_]{1,63}$/.test(code)) {
      setError("code must be snake_case, lowercase, start with a letter");
      return;
    }
    try {
      await api.createDomain({
        code,
        display_name: name || code,
        description: "",
        vocabulary: {},
        required_documents: [],
        rule_module: code,
        decision_prompt_snippet: "",
        thresholds: { low_confidence: 0.8, amount_tolerance: 0.02 },
      });
      setCreating(false);
      setCode("");
      setName("");
      load();
      navigate(`/settings/domains/${code}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const onGenerate = async () => {
    if (genDescription.trim().length < 10) {
      setError("Describe the domain in at least 10 characters.");
      return;
    }
    setError(null);
    setGenBusy(true);
    try {
      const res = await api.generateDomain(genDescription.trim());
      const p = res.proposal;
      if (!p.code) {
        setError("LLM did not return a code for the new domain.");
        return;
      }
      await api.createDomain({
        code: p.code,
        display_name: p.display_name ?? p.code,
        description: p.description ?? "",
        vocabulary: (p.vocabulary as Record<string, unknown>) ?? {},
        required_documents: (p.required_documents as Array<Record<string, string[]>>) ?? [],
        rule_module: p.rule_module ?? p.code,
        decision_prompt_snippet: p.decision_prompt_snippet ?? "",
        thresholds: (p.thresholds as Record<string, unknown>) ?? {
          low_confidence: 0.8,
          amount_tolerance: 0.02,
        },
      });
      setGenerating(false);
      setGenDescription("");
      navigate(`/settings/domains/${p.code}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenBusy(false);
    }
  };

  const onDelete = async (c: string) => {
    if (!confirm(`Delete domain “${c}”? This removes the YAML file from disk.`)) return;
    try {
      await api.deleteDomain(c);
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="p-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Domains</h1>
          <p className="mt-1 text-sm text-ink-dim">
            Domain packs steer extraction prompts, required-document rules, and the
            decisioning snippet. Seeded defaults live under <code>config/domains/</code>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setGenerating((v) => !v);
              setCreating(false);
            }}
            className="rounded-md border border-severity-ok/50 bg-severity-ok/10 px-3 py-1.5 text-sm font-medium text-severity-ok hover:bg-severity-ok/20"
          >
            {generating ? "Cancel" : "Generate with LLM"}
          </button>
          <button
            type="button"
            onClick={() => {
              setCreating((v) => !v);
              setGenerating(false);
            }}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-[#0b0d10] hover:bg-accent-strong"
          >
            {creating ? "Cancel" : "New domain"}
          </button>
        </div>
      </header>

      {generating && (
        <div className="mb-6 rounded-md border border-severity-ok/40 bg-severity-ok/5 p-4">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-medium text-ink">Generate from description</div>
            <span className="text-xs text-ink-faint">
              Gemma 4 will propose code, vocabulary, required docs, and thresholds.
            </span>
          </div>
          <textarea
            value={genDescription}
            onChange={(e) => setGenDescription(e.target.value)}
            rows={4}
            placeholder="e.g. Travel insurance claims for trip cancellation, medical evacuation, and lost baggage. Covers EU and international trips."
            className="w-full rounded-md border border-line bg-bg-base px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <div className="mt-3 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onGenerate}
              disabled={genBusy}
              className="rounded-md bg-severity-ok px-4 py-1.5 text-sm font-medium text-[#0b0d10] hover:bg-severity-ok/90 disabled:opacity-60"
            >
              {genBusy ? "Thinking…" : "Generate & open editor"}
            </button>
          </div>
        </div>
      )}

      {creating && (
        <div className="mb-6 rounded-md border border-line bg-bg-raised p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium uppercase tracking-wide text-ink-dim">
                Code
              </label>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.toLowerCase())}
                placeholder="my_domain"
                className="rounded-md border border-line bg-bg-base px-3 py-2 text-sm outline-none focus:border-accent"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium uppercase tracking-wide text-ink-dim">
                Display name
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My domain"
                className="rounded-md border border-line bg-bg-base px-3 py-2 text-sm outline-none focus:border-accent"
              />
            </div>
          </div>
          <div className="mt-4 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onCreate}
              className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-[#0b0d10] hover:bg-accent-strong"
            >
              Create
            </button>
          </div>
          <p className="mt-2 text-xs text-ink-faint">
            You will be able to edit the full YAML on the next screen. Starter template:
          </p>
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-line bg-bg-base p-2 font-mono text-[11px] text-ink-dim">
            {NEW_DOMAIN_YAML}
          </pre>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-severity-error/40 bg-severity-error/10 px-3 py-2 text-sm text-severity-error">
          {error}
        </div>
      )}

      {domains === null && <div className="text-sm text-ink-dim">Loading…</div>}
      {domains && domains.length === 0 && (
        <div className="text-sm text-ink-dim">No domains configured.</div>
      )}
      {domains && domains.length > 0 && (
        <ul className="divide-y divide-line/60 rounded-md border border-line">
          {domains.map((d) => (
            <li key={d.code} className="flex items-start justify-between gap-4 px-4 py-3 hover:bg-bg-hover">
              <Link to={`/settings/domains/${d.code}`} className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink">{d.display_name}</span>
                  <span className="font-mono text-[11px] text-ink-faint">{d.code}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-ink-dim">
                  {d.description || "(no description)"}
                </p>
              </Link>
              <div className="flex shrink-0 items-center gap-2">
                <Link
                  to={`/settings/domains/${d.code}`}
                  className="rounded-md border border-line px-3 py-1 text-xs text-ink-dim hover:border-accent hover:text-ink"
                >
                  Edit
                </Link>
                <button
                  type="button"
                  onClick={() => onDelete(d.code)}
                  className="rounded-md border border-line px-3 py-1 text-xs text-ink-dim hover:border-severity-error hover:text-severity-error"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
