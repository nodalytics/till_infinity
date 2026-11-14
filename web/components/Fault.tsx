"use client";

import { useEffect, useRef, useState } from "react";

/**
 * What a failed read looks like.
 *
 * **This is the surface a new operator is most likely to meet first.** Start
 * `next dev` without the Python service and every panel on the page is this
 * one - the app renders, the chrome is right, and nothing answers. The old
 * version was a bare paragraph with the start command set in prose, so the
 * only way out of it was to retype a 95-character command out of a sentence.
 *
 * So it names the half that is missing, gives both ways to start it as
 * something you can copy, and offers a retry that re-runs the reads rather
 * than making you reload the page and lose the window you had selected.
 */
export default function Fault({
  detail,
  onRetry,
}: {
  detail: string;
  onRetry: () => void;
}) {
  return (
    <div className="state">
      <div className="card card-wide" role="alert">
        <h2>
          <span className="card-glyph hot" aria-hidden="true">
            <Alert />
          </span>
          The desk API is not answering
        </h2>
        <p className="card-detail mono">{detail}</p>
        <p>
          The page is a shell: every figure on it is a read through this server
          to the Python service, so nothing renders until both halves are up.
          One command starts both and stops both, from the repository root —
          it is what <code>npm run dev</code> runs:
        </p>
        <Command text="bash web/dev.sh" />
        <p>Or the service on its own, if the app is already running:</p>
        <Command text="uv run --extra dashboard uvicorn web.api.main:app --host 127.0.0.1 --port 8787" />
        <div className="card-actions">
          <button type="button" className="btn btn-solid" onClick={onRetry}>
            Try again
          </button>
          <span className="dim" style={{ fontSize: "var(--t-11)" }}>
            Nothing is retried in the background; this re-reads on your word.
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * One command, with a button that copies it.
 *
 * `navigator.clipboard` is unavailable on an insecure origin, and this
 * dashboard is served over plain http on loopback - which some browsers treat
 * as secure and some do not. The `execCommand` path is the one that actually
 * runs about half the time, so it is not a nicety.
 */
export function Command({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current != null) window.clearTimeout(timer.current);
    };
  }, []);

  async function copy() {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      ok = legacyCopy(text);
    }
    if (!ok) return;
    setDone(true);
    if (timer.current != null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setDone(false), 1400);
  }

  return (
    <div className="cmd">
      <code>{text}</code>
      <button
        type="button"
        className="copy"
        data-done={done}
        onClick={copy}
        aria-label={`Copy: ${text}`}
      >
        {done ? "copied" : "copy"}
      </button>
    </div>
  );
}

function legacyCopy(text: string): boolean {
  try {
    const held = document.createElement("textarea");
    held.value = text;
    // Off-screen rather than hidden: a `display: none` textarea cannot be
    // selected, and an unselected one copies nothing.
    held.style.position = "fixed";
    held.style.opacity = "0";
    held.style.pointerEvents = "none";
    document.body.appendChild(held);
    held.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(held);
    return ok;
  } catch {
    return false;
  }
}

/** A bar and a dot. At 13px anything with more than two strokes is a smudge. */
const Alert = () => (
  <svg
    width="13"
    height="13"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
  >
    <path d="M8 3.5v5.2" />
    <path d="M8 12.2h0.01" />
  </svg>
);
