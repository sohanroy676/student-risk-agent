// The signed-in user for this browser tab.
//
// DEV ONLY: the token is pasted in and kept in sessionStorage (gone when the tab closes), which
// script injection can read. A real identity provider with an httpOnly cookie replaces this.
// The role read from the token here only decides which screens to offer; the API checks the
// token's signature and enforces every rule itself.

import type { Role } from "./types";

const KEY = "sra.token";
const ORDER: Role[] = ["admin", "staff", "mentor", "faculty"]; // the API's precedence

export function getToken(): string | null {
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.sessionStorage.setItem(KEY, token);
  } catch {
    // storage blocked: the user simply has to sign in again on the next page load
  }
}

export function clearToken(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // nothing to clear
  }
}

function claims(token: string): Record<string, unknown> | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const base64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const parsed: unknown = JSON.parse(atob(padded));
    return typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** The highest known role in the token, or null when it has none or cannot be read. */
export function roleOf(token: string): Role | null {
  const raw = claims(token)?.roles;
  const roles = Array.isArray(raw) ? raw : typeof raw === "string" ? [raw] : [];
  return ORDER.find((role) => roles.includes(role)) ?? null;
}

export function isExpired(
  token: string,
  nowSeconds = Date.now() / 1000,
): boolean {
  const exp = claims(token)?.exp;
  return typeof exp === "number" && exp <= nowSeconds;
}

export function subjectOf(token: string): string | null {
  const sub = claims(token)?.sub;
  return typeof sub === "string" ? sub : null;
}
