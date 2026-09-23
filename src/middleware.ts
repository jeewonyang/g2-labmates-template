import { NextRequest, NextResponse } from "next/server";

function safeEqual(left: string, right: string): boolean {
  const length = Math.max(left.length, right.length);
  let mismatch = left.length ^ right.length;
  for (let index = 0; index < length; index += 1) {
    mismatch |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
  }
  return mismatch === 0;
}

function suppliedPassword(request: NextRequest): string {
  const authorization = request.headers.get("authorization") || "";
  if (authorization.toLowerCase().startsWith("bearer ")) {
    return authorization.slice(7).trim();
  }
  if (!authorization.toLowerCase().startsWith("basic ")) return "";
  try {
    const decoded = atob(authorization.slice(6).trim());
    const separator = decoded.indexOf(":");
    if (separator < 0 || decoded.slice(0, separator) !== "g2") return "";
    return decoded.slice(separator + 1);
  } catch {
    return "";
  }
}

/**
 * Dashboard Basic auth is opt-in. The normal personal deployment relies on
 * Tailscale identity and has no additional browser prompt. Set
 * DASHBOARD_AUTH_ENABLED=true to add application-level Basic/Bearer auth.
 */
export function middleware(request: NextRequest) {
  if (process.env.DASHBOARD_AUTH_ENABLED?.toLowerCase() !== "true") {
    return NextResponse.next();
  }

  const expected = process.env.OPS_API_TOKEN ?? process.env.CAPTURE_API_TOKEN;
  if (!expected) {
    return new NextResponse("Dashboard access is disabled until OPS_API_TOKEN is configured.", {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    });
  }

  const supplied = suppliedPassword(request);
  if (supplied && safeEqual(supplied, expected)) return NextResponse.next();

  return new NextResponse("Authentication required.", {
    status: 401,
    headers: {
      "Cache-Control": "no-store",
      "WWW-Authenticate": 'Basic realm="G2", charset="UTF-8"',
    },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icon.svg|favicon.ico).*)"],
};
