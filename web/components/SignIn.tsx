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
    <div className="hollow">
      <h2>Sign in to read this desk.</h2>
      <p>
        This dashboard is reachable from outside this machine, so it asks for the shared secret in{" "}
        <code>TILL_DASHBOARD_SECRET</code>.
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
        <button type="submit" className="btn" disabled={busy || !secret}>
          {busy ? "checking" : "sign in"}
        </button>
      </form>
      {failed && (
        <p className="note alarm" role="alert">
          {failed}
        </p>
      )}
    </div>
  );
}
