/**
 * Capture API authentication.
 *
 * Phase 1 uses a single shared bearer token (CAPTURE_API_TOKEN) so a future
 * iOS client can POST captures over HTTPS without a full auth stack. The
 * boundary is deliberately narrow — `authorizeCapture` is the only gate — so
 * it can be swapped for per-user API keys or OAuth/JWT later without touching
 * the capture service or routes.
 */
import { timingSafeEqual } from "crypto";

function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

export type AuthResult =
  | { ok: true }
  | { ok: false; status: 401 | 500; message: string };

function bearer(req: Request, expected: string | undefined, varName: string): AuthResult {
  if (!expected) {
    return { ok: false, status: 500, message: `${varName} is not configured on the server.` };
  }
  const header = req.headers.get("authorization") ?? "";
  const token = header.toLowerCase().startsWith("bearer ")
    ? header.slice(7).trim()
    : "";
  if (!token || !safeEqual(token, expected)) {
    return { ok: false, status: 401, message: "Invalid or missing bearer token." };
  }
  return { ok: true };
}

export function authorizeCapture(req: Request): AuthResult {
  return bearer(req, process.env.CAPTURE_API_TOKEN, "CAPTURE_API_TOKEN");
}

/**
 * Gate for /api/ops — approving and rejecting Agent OS jobs.
 *
 * The dashboard is reachable over Tailscale (your-machine:3000), so anything on
 * the tailnet could otherwise approve triage jobs that file documents into the
 * vault. Approval is a write, so it needs the same bearer gate as capture.
 *
 * Requests from the app's own /ops page are allowed without a token — they are
 * already behind the machine's own session, and requiring one would mean
 * shipping a secret to the client. Everything else must present OPS_API_TOKEN
 * (falling back to CAPTURE_API_TOKEN so one configured secret covers both).
 *
 * The same-origin test requires an EXPLICIT `Sec-Fetch-Site: same-origin`
 * header, which browsers set and will not let cross-site script forge. An
 * earlier version also allowed requests with no Origin header at all, which
 * defeated the gate entirely: curl and any script send neither header, so a
 * plain POST from anywhere on the tailnet was accepted. Absent metadata now
 * means "not a browser", which means "show me a token".
 */
export function authorizeOps(req: Request): AuthResult {
  if (req.headers.get("sec-fetch-site") === "same-origin") {
    return { ok: true };
  }
  return bearer(
    req,
    process.env.OPS_API_TOKEN ?? process.env.CAPTURE_API_TOKEN,
    "OPS_API_TOKEN",
  );
}
