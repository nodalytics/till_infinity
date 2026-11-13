import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { API_TOKEN, COOKIE, refuse } from "@/lib/gate";

/**
 * The only way the browser reaches the Python service.
 *
 * A proxy rather than a rewrite for two reasons. It only exports `GET`, so the
 * read-only promise is in the route table and not in a comment — a POST to
 * `/api/anything` is a 405 before it leaves this process. And it can hold the
 * API credential server-side.
 *
 * **The caller is authenticated before that credential is used.** `refuse`
 * checks the host allowlist (always, whatever else is configured), then
 * refuses outright if the allowlist was widened with no caller secret to check
 * against, then checks the caller's own secret. `TILL_API_TOKEN` is attached
 * only after all three pass: it proves this proxy may call the API and says
 * nothing about who called the proxy, so attaching it to an unauthenticated
 * request would hand the API's authority to whoever arrived.
 */

const API = process.env.TILL_API_URL ?? "http://127.0.0.1:8787";

export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const jar = await cookies();
  const denied = refuse(request, jar.get(COOKIE)?.value ?? "");
  if (denied) {
    return NextResponse.json({ detail: denied.detail }, { status: denied.status });
  }

  const { path } = await context.params;
  const query = new URL(request.url).search;
  const target = `${API}/api/${path.map(encodeURIComponent).join("/")}${query}`;

  const headers: HeadersInit = { accept: "application/json" };
  if (API_TOKEN) headers.authorization = `Bearer ${API_TOKEN}`;

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
