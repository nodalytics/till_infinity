import { createHash, timingSafeEqual } from "node:crypto";

/**
 * Who may talk to the proxy — which is a different question from whether the
 * proxy may talk to the API.
 *
 * **Two secrets, two purposes, and conflating them is a confused deputy.**
 * `TILL_API_TOKEN` is a credential this server *holds*: it proves the proxy
 * may call the API, and says nothing about the caller. `TILL_DASHBOARD_SECRET`
 * is what a caller must *present*. An earlier version attached the API token
 * to every request that arrived and skipped the host check whenever a token
 * was configured, so setting it handed the API's full authority to anyone who
 * could reach Next. Configuring a credential must never widen access.
 *
 * Server-only. Nothing here is imported by a client component, and neither
 * secret has a `NEXT_PUBLIC_` name, so neither can reach a bundle.
 */

/** The cookie a signed-in browser carries. */
export const COOKIE = "till_desk";

const named = (process.env.TILL_WEB_HOSTS ?? "")
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean);

/** Host headers the proxy answers to. Loopback unless the operator widened it. */
export const ALLOWED_HOSTS = named.length ? named : ["127.0.0.1", "localhost", "::1", "[::1]"];

/** What a caller must present. Empty means the dashboard is loopback-only. */
export const CLIENT_SECRET = (process.env.TILL_DASHBOARD_SECRET ?? "").trim();

/** What the proxy presents to the API. Never compared against a caller. */
export const API_TOKEN = (process.env.TILL_API_TOKEN ?? "").trim();

const LOOPBACK = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

/** True when the allowlist names anything that is not this machine. */
const BIND = (process.env.TILL_WEB_BIND ?? "").trim().toLowerCase();

/**
 * Is this process reachable from somewhere other than this machine?
 *
 * **Two sources, because the `Host` header is not one of them.** `Host` is
 * whatever the caller typed: a request from anywhere carrying
 * `Host: 127.0.0.1` satisfies the allowlist, so the allowlist is a
 * DNS-rebinding defence and never a proof of locality. It was the only input
 * here, which meant a server bound to `0.0.0.0` with no caller secret served
 * a live account to anyone who spelled the header correctly.
 *
 * So exposure is read from configuration the **operator** sets and the caller
 * cannot: the hosts this answers to, and the address it was bound to.
 *
 * **An unset `TILL_WEB_BIND` counts as exposed.** It used to count as
 * loopback, which made a missing variable grant access - the third time that
 * shape has appeared in this file, after a token standing in for client auth
 * and a `Host` header standing in for locality. A value that is absent is not
 * a value that says "local"; it is a value nobody set. `package.json` sets it
 * beside its `-H` flag, the image sets a deliberately non-loopback default,
 * and `deploy-web.sh` passes the real host-side publish address - so every
 * supported path states it, and anything that does not is asked for a caller
 * secret.
 */
export const EXPOSED =
  ALLOWED_HOSTS.some((host) => !LOOPBACK.has(host)) || !LOOPBACK.has(BIND);

/**
 * The Host header without its port, with a bracketed IPv6 literal kept whole.
 *
 * Splitting on `:` alone would turn `[::1]:3000` into `[`, which then matches
 * nothing and looks like a correctly refused request.
 */
export function hostOf(request: Request): string {
  const raw = request.headers.get("host") ?? "";
  if (raw.startsWith("[")) {
    const close = raw.indexOf("]");
    return close === -1 ? raw : raw.slice(0, close + 1);
  }
  return raw.split(":")[0] ?? "";
}

/** Always enforced, token or no token. */
export function hostAllowed(request: Request): boolean {
  return ALLOWED_HOSTS.includes(hostOf(request));
}

/**
 * Constant-time comparison of two secrets.
 *
 * Both sides are hashed first so the buffers are always 32 bytes:
 * `timingSafeEqual` throws on a length mismatch, and throwing on the wrong
 * length is itself an oracle for the length.
 */
export function sameSecret(offered: string, expected: string): boolean {
  if (!expected || !offered) return false;
  const a = createHash("sha256").update(offered, "utf8").digest();
  const b = createHash("sha256").update(expected, "utf8").digest();
  return timingSafeEqual(a, b);
}

/** The bearer a caller offered, if it offered one. */
export function bearerOf(request: Request): string {
  const header = request.headers.get("authorization") ?? "";
  return header.toLowerCase().startsWith("bearer ") ? header.slice(7) : "";
}

export type Refusal = { status: number; detail: string };

/**
 * Whether this request may be proxied. `null` means yes.
 *
 * The order is the point: host first, then a configuration check that fails
 * closed, then the caller's own credential. The API token is attached by the
 * caller of this function and only after it returns `null`.
 */
export function refuse(request: Request, cookie: string): Refusal | null {
  if (!hostAllowed(request)) {
    return {
      status: 403,
      detail:
        "This dashboard serves a live trading account and answers a fixed set of " +
        "hosts. Add this one to TILL_WEB_HOSTS if that is deliberate.",
    };
  }
  if (EXPOSED && !CLIENT_SECRET) {
    // Fail closed. TILL_WEB_HOSTS names something off this machine and no
    // caller credential is configured, so there is nothing to authenticate
    // against and the API token would be handed to whoever arrived.
    return {
      status: 503,
      detail:
        "TILL_WEB_HOSTS names a non-loopback host but TILL_DASHBOARD_SECRET is not " +
        "set, so there is no way to tell who is calling. Set it, or drop the host.",
    };
  }
  if (API_TOKEN && !CLIENT_SECRET) {
    // **Never lend a held credential to a caller nobody checked.** This is the
    // confused deputy that shipped once already, in its general form: if the
    // proxy holds something that grants access to the API, it may only pass it
    // on behalf of someone it authenticated. With no caller secret configured
    // there is no one to authenticate, so there is nothing this token may be
    // used for.
    return {
      status: 503,
      detail:
        "TILL_API_TOKEN is set with no TILL_DASHBOARD_SECRET to check a caller " +
        "against. The proxy will not present its credential for a caller it " +
        "cannot authenticate. Set TILL_DASHBOARD_SECRET, or unset TILL_API_TOKEN " +
        "and let the API enforce its own loopback-peer check.",
    };
  }
  if (!CLIENT_SECRET) return null;
  if (sameSecret(cookie, CLIENT_SECRET) || sameSecret(bearerOf(request), CLIENT_SECRET)) {
    return null;
  }
  return { status: 401, detail: "sign in to read this desk" };
}
