import { clearToken, getToken } from "./session";
import type { CaseAction, CaseDetail, CasePage, CaseState } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function messageFor(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
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
