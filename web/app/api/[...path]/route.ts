import { NextResponse } from "next/server";

/**
 * The only way the browser reaches the Python service.
 *
 * A proxy rather than a rewrite for two reasons. It can attach the shared
 * secret **on the server**, so `TILL_API_TOKEN` never reaches a browser, a
 * devtools network tab or a screenshot. And it only exports `GET`, so the
 * read-only promise is enforced by the route table rather than by a comment:
 * a POST to `/api/anything` is a 405 before it leaves this process.
 *
 * The browser therefore knows one host, its own. Nothing about the desk's
 * record crosses an origin.
 */

const API = process.env.TILL_API_URL ?? "http://127.0.0.1:8787";
const TOKEN = process.env.TILL_API_TOKEN ?? "";

/**
 * Host headers this proxy answers to.
 *
 * Binding Next to 127.0.0.1 is necessary and not sufficient: a hostname that
 * resolves to loopback reaches it from any page the operator's browser opens,
 * and this proxy forwards to an API whose own auth is skipped precisely
 * because it believed it was only reachable locally. So the proxy enforces the
 * same boundary the API assumes.
 *
 * **The check is unconditional, and an earlier version made it conditional on
 * a token being set.** That was a confused deputy: `TILL_API_TOKEN` is a
 * credential *this process* holds for its hop to the API, and attaching it to
 * whoever happens to arrive grants them the API's whole authority. A token
 * says the proxy may talk to the API. It says nothing about who is talking to
 * the proxy, so it can never stand in for checking that.
 *
 * Deliberate exposure is therefore an explicit act: set `TILL_WEB_HOSTS` to
 * the host names this should answer to. There is no client authentication at
 * this layer yet, so anyone who can reach a listed host reaches the desk's
 * record - the README says so rather than implying the token covers it.
 */
const LOCAL = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);
const ALLOWED = new Set(
  (process.env.TILL_WEB_HOSTS ?? "")
    .split(",")
    .map((name) => name.trim().toLowerCase())
    .filter(Boolean),
);

export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const host = (request.headers.get("host") ?? "").split(":")[0]?.toLowerCase() ?? "";
  if (!LOCAL.has(host) && !ALLOWED.has(host)) {
    return NextResponse.json(
      {
        detail:
          "This dashboard serves a live trading account and answers on loopback " +
          "only. Reaching it from elsewhere is a deliberate act: list the host " +
          "names in TILL_WEB_HOSTS. Note that there is no client authentication " +
          "at this layer, so anyone who can reach a listed host reaches the desk.",
      },
      { status: 403 },
    );
  }

  const { path } = await context.params;
  const query = new URL(request.url).search;
  const target = `${API}/api/${path.map(encodeURIComponent).join("/")}${query}`;

  const headers: HeadersInit = { accept: "application/json" };
  if (TOKEN) headers.authorization = `Bearer ${TOKEN}`;

  try {
    const answer = await fetch(target, { headers, cache: "no-store" });
    const body = await answer.text();
    return new NextResponse(body, {
      status: answer.status,
      headers: { "content-type": answer.headers.get("content-type") ?? "application/json" },
    });
  } catch (error) {
    // A service that is not running is the common case, and the page says so
    // rather than rendering zeros over a dead API.
    return NextResponse.json(
      {
        detail: `The desk API at ${API} is not answering (${
          error instanceof Error ? error.message : String(error)
        }).`,
      },
      { status: 502 },
    );
  }
}
