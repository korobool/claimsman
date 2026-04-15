import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

type Schema = {
  doc_type: string;
  display_name: string;
  domains: string[];
  description: string;
  fields: unknown[];
  yaml: string;
};

export default function Schemas() {
  const [schemas, setSchemas] = useState<Schema[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [editorYaml, setEditorYaml] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [generating, setGenerating] = useState(false);
  const [proposal, setProposal] = useState<{
    yaml: string;
    ocr_preview: string;
  } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.listSchemas();
      setSchemas(r.schemas);
      if (!selected && r.schemas[0]) {
        setSelected(r.schemas[0].doc_type);
        setEditorYaml(r.schemas[0].yaml);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selected]);

  useEffect(() => {
    load();
  }, [load]);

  const onSelect = (doc_type: string) => {
    setSelected(doc_type);
    const s = schemas?.find((x) => x.doc_type === doc_type);
    setEditorYaml(s?.yaml ?? "");
    setProposal(null);
    setSavedAt(null);
  };

  const onSave = async () => {
    if (!selected) return;
    setError(null);
    try {
      await api.updateSchemaYaml(selected, editorYaml);
      setSavedAt(new Date().toLocaleTimeString());
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const onGenerate = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(null);
    setGenerating(true);
    try {
      const res = await api.generateSchemaFromFile(file, "health_insurance");
      setProposal({ yaml: res.yaml, ocr_preview: res.ocr_text_preview });
      setEditorYaml(res.yaml);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-line px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Schemas</h1>
          <p className="text-sm text-ink-dim">
            Document-type schemas steer the extractor. Edit YAML or generate a new
            schema from a sample document.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            accept="image/*,application/pdf,.docx"
            className="hidden"
            onChange={onGenerate}
          />
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={generating}
            className="rounded-md border border-severity-ok/50 bg-severity-ok/10 px-3 py-1.5 text-sm font-medium text-severity-ok hover:bg-severity-ok/20 disabled:opacity-50"
          >
            {generating ? "Analyzing…" : "Generate from sample"}
          </button>
          {selected && (
            <button
              type="button"
              onClick={onSave}
              className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-[#0b0d10] hover:bg-accent-strong"
            >
              Save
            </button>
          )}
          {savedAt && <span className="text-xs text-ink-faint">saved {savedAt}</span>}
        </div>
      </header>

      {error && (
        <div className="border-b border-severity-error/30 bg-severity-error/10 px-6 py-2 text-sm text-severity-error">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="w-64 shrink-0 overflow-auto border-r border-line bg-bg-raised">
          {schemas?.map((s) => (
            <button
              key={s.doc_type}
              type="button"
              onClick={() => onSelect(s.doc_type)}
              className={[
                "flex w-full items-center justify-between px-4 py-2 text-left text-sm",
                selected === s.doc_type ? "bg-accent/15 text-ink" : "text-ink-dim hover:bg-bg-hover",
              ].join(" ")}
            >
              <span className="truncate">{s.display_name}</span>
              <span className="font-mono text-[10px] text-ink-faint">{s.doc_type}</span>
            </button>
          ))}
        </aside>

        <main className="grid min-h-0 flex-1 grid-cols-2 gap-4 p-6">
          <div className="flex min-h-0 flex-col">
            <div className="mb-2 text-xs uppercase tracking-wide text-ink-faint">
              YAML editor
            </div>
            <textarea
              value={editorYaml}
              onChange={(e) => setEditorYaml(e.target.value)}
              spellCheck={false}
              className="min-h-0 flex-1 resize-none rounded-md border border-line bg-bg-raised p-3 font-mono text-xs text-ink outline-none focus:border-accent"
            />
          </div>
          <div className="flex min-h-0 flex-col overflow-auto">
            {proposal && (
              <section className="mb-4 rounded-md border border-severity-ok/40 bg-severity-ok/5 p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-severity-ok">
                  LLM proposal (from sample)
                </div>
                <div className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-ink-dim">
                  {proposal.ocr_preview || "(no OCR text)"}
                </div>
                <p className="mt-3 text-xs text-ink-dim">
                  The proposed schema has been written into the editor on the left.
                  Review it, adjust as needed, and Save to persist.
                </p>
              </section>
            )}
            <section className="rounded-md border border-line bg-bg-raised p-4 text-xs">
              <div className="text-xs uppercase tracking-wide text-ink-faint">Tips</div>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-ink-dim">
                <li>
                  Keep <code>doc_type</code> matching the filename (snake_case).
                </li>
                <li>
                  Use <code>list[object]</code> for tables; list sub-fields under{" "}
                  <code>fields</code>.
                </li>
                <li>
                  Include domain codes in <code>domains</code> so classification uses
                  this schema.
                </li>
              </ul>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
