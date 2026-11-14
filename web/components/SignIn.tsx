"use client";

import { useState } from "react";

/**
 * Shown when the proxy answers 401, which only happens where a dashboard
 * secret is configured.
 *
 * The secret goes to `/session`, which compares it in constant time and sets
 * an httpOnly cookie. It is never held in component state longer than the
 * submit, never put in a URL, and never reaches the data proxy — the cookie
 * does that.
 */
export default function SignIn({ onDone }: { onDone: () => void }) {
  const [secret, setSecret] = useState("");
  const [failed, setFailed] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed("");
    try {
      const answer = await fetch("/session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ secret }),
      });
      if (answer.ok) {
        setSecret("");
        onDone();
        return;
      }
      const body: unknown = await answer.json().catch(() => null);
      setFailed(
        body && typeof body === "object" && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : `sign-in failed (${answer.status})`,
      );
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="state">
      <div className="card">
        <h2>
          <span className="card-glyph" aria-hidden="true">
            <Lock />
          </span>
          Sign in to read this desk
        </h2>
        <p>
          This dashboard is reachable from outside this machine, so it asks for the shared secret
          in <code>TILL_DASHBOARD_SECRET</code>. One shared secret is not a user system: there are
          no accounts and no rotation, and a cookie lasts a day.
        </p>
        <form onSubmit={submit} style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="field"
            type="password"
            value={secret}
            autoFocus
            autoComplete="current-password"
            placeholder="shared secret"
            aria-label="Shared secret"
            onChange={(event) => setSecret(event.target.value)}
          />
          <button type="submit" className="btn btn-solid" disabled={busy || !secret}>
            {busy ? "checking" : "sign in"}
          </button>
        </form>
        {failed && (
          <p className="card-detail alarm" role="alert" style={{ marginTop: 12, marginBottom: 0 }}>
            {failed}
          </p>
        )}
      </div>
    </div>
  );
}

const Lock = () => (
  <svg
    width="13"
    height="13"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <rect x="3.5" y="7" width="9" height="6.5" rx="1" />
    <path d="M5.75 7V5.25a2.25 2.25 0 014.5 0V7" />
  </svg>
);
