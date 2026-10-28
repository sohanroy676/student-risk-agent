"use client";

import { useEffect, useState } from "react";

import { clearToken, getToken, isExpired, roleOf, subjectOf } from "./session";
import type { Role } from "./types";

export interface Session {
  ready: boolean; // false until the browser has been asked (storage is not readable on the server)
  role: Role | null;
  subject: string | null;
}

/** Who is signed in. An expired or role-less token counts as signed out. */
export function useSession(): Session {
  const [session, setSession] = useState<Session>({
    ready: false,
    role: null,
    subject: null,
  });
  useEffect(() => {
    const token = getToken();
    if (token && isExpired(token)) clearToken();
    const valid = token && !isExpired(token) ? token : null;
    setSession({
      ready: true,
      role: valid ? roleOf(valid) : null,
      subject: valid ? subjectOf(valid) : null,
    });
  }, []);
  return session;
}
