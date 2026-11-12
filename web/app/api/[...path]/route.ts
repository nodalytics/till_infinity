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
 * same boundary the API assumes. With a token configured the API checks every
 * request itself, and the host check steps aside.
 */
const LOCAL = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  if (!TOKEN) {
    const host = (request.headers.get("host") ?? "").split(":")[0] ?? "";
    if (!LOCAL.has(host)) {
      return NextResponse.json(
        {
          detail:
            "This dashboard serves a live trading account and is loopback-only. " +
            "To reach it from elsewhere set TILL_WEB_TOKEN on the API and " +
            "TILL_API_TOKEN here.",
        },
        { status: 403 },
      );
    }
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
