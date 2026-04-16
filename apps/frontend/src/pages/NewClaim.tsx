import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

const DOMAIN_OPTIONS = [
  { value: "health_insurance", label: "Health insurance" },
  { value: "motor_insurance", label: "Motor insurance" },
];

export default function NewClaim() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [claimantName, setClaimantName] = useState("");
  const [policyNumber, setPolicyNumber] = useState("");
  const [title, setTitle] = useState("");
  const [domain, setDomain] = useState("health_insurance");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const addFiles = useCallback((newFiles: FileList | File[]) => {
    setFiles((prev) => {
      const byKey = new Map<string, File>();
      for (const f of prev) byKey.set(`${f.name}:${f.size}`, f);
      for (const f of Array.from(newFiles)) byKey.set(`${f.name}:${f.size}`, f);
      return Array.from(byKey.values());
    });
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLLabelElement>) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
    },
    [addFiles],
  );

  const removeFile = (name: string, size: number) => {
    setFiles((prev) => prev.filter((f) => !(f.name === name && f.size === size)));
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (files.length === 0) {
      setError("Attach at least one file.");
      return;
    }
    setSubmitting(true);
    try {
      const form = new FormData();
      for (const f of files) form.append("files", f);
      if (claimantName) form.append("claimant_name", claimantName);
      if (policyNumber) form.append("policy_number", policyNumber);
      if (title) form.append("title", title);
      form.append("domain", domain);
      if (notes) form.append("notes", notes);
      const created = await api.createClaim(form);
      navigate(`/?new=${created.code}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <h1 className="text-xl font-semibold tracking-tight">New claim</h1>
      <p className="mt-2 text-sm text-ink-dim">
        Upload the documents that make up this claim. Classification, extraction, and decision
        proposals run automatically in later milestones; for now we persist and index.
      </p>

      <form className="mt-8 space-y-6" onSubmit={onSubmit}>
        <label
          htmlFor="files"
          className={[
            "flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
            dragOver
              ? "border-accent bg-accent/5"
              : "border-line bg-bg-raised hover:border-accent/60",
          ].join(" ")}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="mb-3 h-8 w-8 text-ink-dim"
          >
            <path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            <path d="M12 4v12" />
            <path d="M7 9l5-5 5 5" />
          </svg>
          <span className="text-sm font-medium">
            Drop files here or{" "}
            <button
              type="button"
              className="text-accent underline-offset-2 hover:underline"
              onClick={() => fileInputRef.current?.click()}
            >
              browse
            </button>
          </span>
          <span className="mt-1 text-xs text-ink-faint">
            PDF, images, DOCX — up to 50 MB per file
          </span>
          <input
            ref={fileInputRef}
            id="files"
            type="file"
            multiple
            className="hidden"
            accept="image/*,application/pdf,.docx"
            onChange={(e) => {
              if (e.target.files) {
                const picked = Array.from(e.target.files);
                e.target.value = "";
                addFiles(picked);
              }
            }}
          />
        </label>

        {files.length > 0 && (
          <ul className="space-y-1 rounded-md border border-line bg-bg-raised p-3">
            {files.map((f) => (
              <li
                key={`${f.name}:${f.size}`}
                className="flex items-center justify-between text-sm"
              >
                <span className="truncate pr-3">{f.name}</span>
                <span className="flex items-center gap-3 text-xs text-ink-dim">
                  {formatBytes(f.size)}
                  <button
                    type="button"
                    className="rounded px-2 py-0.5 text-ink-dim hover:bg-bg-hover hover:text-severity-error"
                    onClick={() => removeFile(f.name, f.size)}
                  >
                    remove
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Claimant name" value={claimantName} onChange={setClaimantName} />
          <Field label="Policy number" value={policyNumber} onChange={setPolicyNumber} />
          <Field label="Claim title (optional)" value={title} onChange={setTitle} />
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium uppercase tracking-wide text-ink-dim">
              Domain
            </label>
            <select
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="rounded-md border border-line bg-bg-raised px-3 py-2 text-sm outline-none focus:border-accent"
            >
              {DOMAIN_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium uppercase tracking-wide text-ink-dim">
            Notes
          </label>
          <textarea
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="rounded-md border border-line bg-bg-raised px-3 py-2 text-sm outline-none focus:border-accent"
            placeholder="Anything a reviewer should know…"
          />
        </div>

        {error && (
          <div className="rounded-md border border-severity-error/40 bg-severity-error/10 px-3 py-2 text-sm text-severity-error">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-3">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-[#0b0d10] hover:bg-accent-strong disabled:opacity-50"
          >
            {submitting ? "Uploading…" : "Create claim"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium uppercase tracking-wide text-ink-dim">
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-line bg-bg-raised px-3 py-2 text-sm outline-none focus:border-accent"
      />
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
