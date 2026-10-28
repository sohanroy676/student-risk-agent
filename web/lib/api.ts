import { clearToken, getToken } from "./session";
import type {
  CaseAction,
  CaseDetail,
  CasePage,
  CaseState,
  GateResult,
  ModelCard,
  ModelRelease,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function codes(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
}

function messageFor(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (typeof detail === "object" && detail !== null) {
    // the promotion gate answers 409 with the blocks nobody has signed off
    const gate = detail as { unresolved?: unknown; hard_failures?: unknown };
    const open = [...codes(gate.unresolved), ...codes(gate.hard_failures)];
    if (open.length > 0)
      return `the gate still blocks this release: ${open.join(", ")}`;
  }
  if (status === 403) return "not allowed";
  if (status === 422) return "the request was not accepted";
  return "something went wrong";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init.body) headers["Content-Type"] = "application/json";
  const reply = await fetch(`/backend${path}`, { ...init, headers });
  if (reply.status === 401) {
    clearToken();
    window.location.assign("/login");
    throw new ApiError(401, "signed out");
  }
  if (!reply.ok) {
    const body: unknown = await reply.json().catch(() => null);
    const detail =
      typeof body === "object" && body !== null
        ? (body as { detail?: unknown }).detail
        : null;
    throw new ApiError(reply.status, messageFor(reply.status, detail));
  }
  return (await reply.json()) as T;
}

export function loadCaseload(params: {
  state?: CaseState;
  includeClosed?: boolean;
  limit?: number;
  offset?: number;
}): Promise<CasePage> {
  const query = new URLSearchParams();
  if (params.state) query.set("state", params.state);
  if (params.includeClosed) query.set("include_closed", "true");
  query.set("limit", String(params.limit ?? 50));
  query.set("offset", String(params.offset ?? 0));
  return request<CasePage>(`/api/caseload?${query}`);
}

export function loadCase(id: number): Promise<CaseDetail> {
  return request<CaseDetail>(`/api/cases/${id}`);
}

export function actOnCase(
  id: number,
  action: CaseAction,
): Promise<{ id: number; state: CaseState }> {
  return request(`/api/cases/${id}/actions`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export function saveDraft(
  id: number,
  message: string,
): Promise<{ id: number; version: number }> {
  return request(`/api/cases/${id}/draft`, {
    method: "PUT",
    body: JSON.stringify({ message }),
  });
}

export function loadReleases(): Promise<ModelRelease[]> {
  return request<ModelRelease[]>("/api/admin/models");
}

export function loadRelease(release: number): Promise<ModelRelease> {
  return request<ModelRelease>(`/api/admin/models/${release}`);
}

export function loadModelCard(release: number): Promise<ModelCard> {
  return request<ModelCard>(`/api/admin/models/${release}/card`);
}

export function promoteRelease(
  release: number,
  body: { reason: string; covers: string[] },
): Promise<GateResult> {
  return request<GateResult>(`/api/admin/models/${release}/promote`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
