/** Minimal ops API client for the take-offline admin page. */

const OPS_TOKEN_KEY = "tess_ops_admin_token";

export function getOpsToken(): string | null {
  const value = localStorage.getItem(OPS_TOKEN_KEY);
  return value?.trim() || null;
}

export function setOpsToken(token: string): void {
  localStorage.setItem(OPS_TOKEN_KEY, token.trim());
}

export function clearOpsToken(): void {
  localStorage.removeItem(OPS_TOKEN_KEY);
}

export class OpsApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "OpsApiError";
    this.status = status;
  }
}

function authHeaders(): HeadersInit {
  const token = getOpsToken();
  if (!token) {
    throw new OpsApiError(401, "No admin token set");
  }
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/json",
  };
}

async function opsFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText || "Request failed";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail != null) {
        detail = JSON.stringify(body.detail);
      }
    } catch {
      // keep statusText
    }
    throw new OpsApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type OpsProvider = {
  id: string;
  name: string;
  type: string;
  enabled: boolean;
  simulate_unhealthy: boolean;
  chaos?: { kind?: string; enabled?: boolean };
  base_url: string;
  ws_base_url?: string | null;
};

export type OpsRoutingPayload = {
  routing: {
    active_provider_id: string | null;
    sessions_dropped_last?: number;
    last_failover_from?: string | null;
    last_failover_to?: string | null;
  };
  active?: {
    active_provider_id: string | null;
    base_url?: string | null;
    ws_base_url?: string | null;
  };
};

export function fetchRouting(): Promise<OpsRoutingPayload> {
  return opsFetch<OpsRoutingPayload>("/ops/routing");
}

export function fetchProviders(): Promise<OpsProvider[]> {
  return opsFetch<OpsProvider[]>("/ops/providers");
}

export function simulateUnhealthy(
  providerId: string,
  enabled: boolean,
): Promise<OpsProvider> {
  const q = enabled ? "true" : "false";
  return opsFetch<OpsProvider>(
    `/ops/providers/${encodeURIComponent(providerId)}/simulate-unhealthy?enabled=${q}`,
    { method: "POST" },
  );
}

export function clearChaos(providerId: string): Promise<{ status: string }> {
  return opsFetch<{ status: string }>(
    `/ops/chaos/${encodeURIComponent(providerId)}`,
    { method: "DELETE" },
  );
}

export function forceActive(providerId: string): Promise<unknown> {
  return opsFetch(`/ops/routing/active/${encodeURIComponent(providerId)}`, {
    method: "POST",
  });
}

export function probeNow(): Promise<unknown> {
  return opsFetch("/ops/probe", { method: "POST" });
}
