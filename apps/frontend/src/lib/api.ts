export interface HealthResponse {
  status: string;
  version: string;
  env: string;
}

export interface SystemInfo {
  name: string;
  version: string;
  env: string;
  ollama: {
    base_url: string;
    default_model: string;
  };
}

export interface ClaimSummary {
  id: string;
  code: string;
  title: string | null;
  claimant_name: string | null;
  policy_number: string | null;
  domain: string;
  status: string;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
  upload_count: number;
}

export interface ClaimUpload {
  id: string;
  claim_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
}

export interface OcrLine {
  text: string;
  bbox: number[];
  confidence: number;
  polygon: number[][] | null;
}

export interface ClaimPage {
  id: string;
  page_index: number;
  classification: string | null;
  confidence: number | null;
  has_image: boolean;
  text_layer_used: boolean;
  ocr_preview: string | null;
  ocr_text: string | null;
  line_count: number;
  width: number | null;
  height: number | null;
  ocr_lines: OcrLine[] | null;
}

export interface ExtractedField {
  id: string;
  document_id: string;
  schema_key: string;
  value: unknown;
  confidence: number | null;
  llm_model: string | null;
}

export interface ClaimDocument {
  id: string;
  doc_type: string;
  display_name: string | null;
  page_count: number;
  pages: ClaimPage[];
  extracted_fields: ExtractedField[];
}

export interface Finding {
  id: string;
  claim_id: string;
  severity: "info" | "warning" | "error";
  code: string;
  message: string;
  refs: Record<string, unknown> | null;
}

export type DecisionOutcome =
  | "approve"
  | "partial_approve"
  | "deny"
  | "needs_info";

export interface ClaimDecision {
  id: string;
  claim_id: string;
  kind: string;
  outcome: DecisionOutcome;
  amount: number | null;
  currency: string | null;
  rationale_md: string | null;
  is_proposed: boolean;
  llm_model: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  created_at: string | null;
}

export interface ClaimDetail extends ClaimSummary {
  uploads: ClaimUpload[];
  documents: ClaimDocument[];
  findings: Finding[];
  findings_by_severity: Record<"info" | "warning" | "error", Finding[]>;
  findings_summary: { error: number; warning: number; info: number };
  proposed_decision: ClaimDecision | null;
  confirmed_decision: ClaimDecision | null;
  decisions: ClaimDecision[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", ...init });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${path} ${res.status}${body ? `: ${body}` : ""}`);
  }
  return (await res.json()) as T;
}

export interface DevState {
  app: {
    name: string;
    version: string;
    env: string;
    port: number;
    base_url: string;
  };
  milestone: {
    id: string;
    label: string;
    phase: string;
    description: string;
    completed_milestones: string[];
    next_milestones: string[];
  };
  git: {
    head?: string;
    branch?: string;
    commits?: Array<{ sha: string; author: string; when: string; subject: string }>;
    error?: string;
  };
  config: {
    schemas: { count: number; doc_types: string[] };
    domains: { count: number; codes: string[] };
  };
  db: {
    claims: number;
    uploads: number;
    documents: number;
    pages: number;
    extracted_fields: number;
  };
  recent_claims: Array<{
    id: string;
    code: string;
    title: string | null;
    claimant_name: string | null;
    domain: string;
    status: string;
    created_at: string | null;
  }>;
  ollama: {
    reachable: boolean;
    url: string;
    default_model: string;
    model_count?: number;
    models_sample?: Array<{ name: string; size: number }>;
    error?: string;
  };
}

export interface Domain {
  code: string;
  display_name: string;
  description: string;
  vocabulary: Record<string, unknown>;
  required_documents: Array<Record<string, string[]>>;
  rule_module: string;
  decision_prompt_snippet: string;
  thresholds: Record<string, unknown>;
  yaml: string;
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${init?.method ?? "GET"} ${path} ${res.status}${body ? `: ${body}` : ""}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/api/v1/system/healthz"),
  info: () => request<SystemInfo>("/api/v1/system/info"),
  listClaims: () => request<{ claims: ClaimSummary[] }>("/api/v1/claims"),
  getClaim: (id: string) => request<ClaimDetail>(`/api/v1/claims/${id}`),
  createClaim: async (form: FormData): Promise<ClaimDetail> => {
    const res = await fetch("/api/v1/claims", {
      method: "POST",
      body: form,
      credentials: "same-origin",
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`POST /api/v1/claims ${res.status}${body ? `: ${body}` : ""}`);
    }
    return (await res.json()) as ClaimDetail;
  },
  listDomains: () => requestJson<{ domains: Domain[] }>("/api/v1/domains"),
  getDomain: (code: string) => requestJson<Domain>(`/api/v1/domains/${code}`),
  updateDomainYaml: (code: string, yaml: string) =>
    requestJson<Domain>(`/api/v1/domains/${code}/yaml`, {
      method: "PUT",
      body: JSON.stringify({ yaml }),
    }),
  createDomain: (body: Partial<Domain>) =>
    requestJson<Domain>("/api/v1/domains", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteDomain: (code: string) =>
    requestJson<void>(`/api/v1/domains/${code}`, { method: "DELETE" }),
  generateDomain: (description: string) =>
    requestJson<{ proposal: Partial<Domain>; yaml: string; raw_response: string }>(
      "/api/v1/domains/generate",
      { method: "POST", body: JSON.stringify({ description }) },
    ),
  devState: () => requestJson<DevState>("/api/v1/dev/state"),
  confirmDecision: (
    claimId: string,
    body: {
      outcome: DecisionOutcome;
      amount?: number | null;
      currency?: string | null;
      rationale_md?: string | null;
      reviewer?: string;
    },
  ) =>
    requestJson<{ claim_status: string; decision: ClaimDecision }>(
      `/api/v1/claims/${claimId}/decision/confirm`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  reopenDecision: (claimId: string) =>
    requestJson<{ claim_status: string }>(
      `/api/v1/claims/${claimId}/decision/reopen`,
      { method: "POST", body: "{}" },
    ),
};
