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

export interface ClaimDetail extends ClaimSummary {
  uploads: Array<{
    id: string;
    claim_id: string;
    filename: string;
    mime_type: string;
    size_bytes: number;
    sha256: string;
  }>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", ...init });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${path} ${res.status}${body ? `: ${body}` : ""}`);
  }
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
};
