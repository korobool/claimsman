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

async function request<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) {
    throw new Error(`${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/api/v1/system/healthz"),
  info: () => request<SystemInfo>("/api/v1/system/info"),
};
