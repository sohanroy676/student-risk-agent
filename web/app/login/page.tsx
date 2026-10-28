"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { isExpired, roleOf, setToken } from "@/lib/session";

// DEV ONLY sign-in: paste a token minted by scripts/dev_token.py. Turned on at build time with
// NEXT_PUBLIC_DEV_TOKEN_LOGIN=true; without it this page offers nothing. The real sign-in will
// go through the college's identity provider.
const DEV_LOGIN = process.env.NEXT_PUBLIC_DEV_TOKEN_LOGIN === "true";

export default function Login() {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const token = value.trim();
    if (!token || roleOf(token) === null) {
      setError(
        "That token has no role this app knows (admin, staff, mentor or faculty).",
      );
    } else if (isExpired(token)) {
      setError("That token has expired.");
    } else {
      setToken(token);
      router.replace("/");
    }
  };

  if (!DEV_LOGIN) {
    return (
      <main className="page narrow">
        <h1>Sign in</h1>
        <p>Sign-in is not configured for this installation.</p>
      </main>
    );
  }
  return (
    <main className="page narrow">
      <h1>Sign in</h1>
      <p className="muted">Development sign-in: paste an access token.</p>
      <form onSubmit={submit}>
        <label htmlFor="token">Access token</label>
        <textarea
          id="token"
          rows={5}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        {error && <p role="alert">{error}</p>}
        <button type="submit">Sign in</button>
      </form>
    </main>
  );
}
