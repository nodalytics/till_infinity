import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { CLIENT_SECRET, COOKIE, hostAllowed, sameSecret } from "@/lib/gate";

/**
 * Signing in to the dashboard, and signing out of it.
 *
 * One shared secret, not a user system — which is the size the brief asked
 * for. The cookie carries the secret itself, so a stolen cookie is a stolen
 * secret; it is `httpOnly` so page scripts cannot read it, `SameSite=Strict`
 * so another site cannot make the browser send it on a cross-site request to
 * the GET-only proxy, and `Secure` whenever the request arrived over https.
 *
 * There is no rotation, no expiry beyond the cookie's own, no lockout and no
 * rate limit. Those are the limits of a shared secret and they are written
 * down rather than implied.
 */

const DAY = 60 * 60 * 24;

export async function POST(request: Request) {
  if (!hostAllowed(request)) {
    return NextResponse.json({ detail: "unknown host" }, { status: 403 });
  }
  if (!CLIENT_SECRET) {
    return NextResponse.json(
      {
        detail:
          "No TILL_DASHBOARD_SECRET is configured, so there is nothing to sign in to. " +
          "The dashboard is loopback-only in this configuration.",
      },
      { status: 409 },
    );
  }

  let offered = "";
  try {
    const body: unknown = await request.json();
    if (body && typeof body === "object" && "secret" in body) {
      offered = String((body as { secret: unknown }).secret ?? "");
    }
  } catch {
    // Not JSON. Treated as an empty secret, which fails the comparison below.
  }

  if (!sameSecret(offered, CLIENT_SECRET)) {
    return NextResponse.json({ detail: "that is not the secret" }, { status: 401 });
  }

  const jar = await cookies();
  jar.set(COOKIE, CLIENT_SECRET, {
    httpOnly: true,
    sameSite: "strict",
    secure: new URL(request.url).protocol === "https:",
    path: "/",
    maxAge: DAY,
  });
  return NextResponse.json({ ok: true });
}

export async function DELETE(request: Request) {
  if (!hostAllowed(request)) {
    return NextResponse.json({ detail: "unknown host" }, { status: 403 });
  }
  const jar = await cookies();
  jar.delete(COOKIE);
  return NextResponse.json({ ok: true });
}
