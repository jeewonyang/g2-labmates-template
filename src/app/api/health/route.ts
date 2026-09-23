import { NextResponse } from "next/server";

/**
 * Process-local liveness marker for Tailscale and the Windows watchdog.
 * The marker prevents an unrelated service on port 3000 from being mistaken
 * for G2. It intentionally performs no database or external-network work.
 */
export async function GET() {
  return NextResponse.json(
    { ok: true, service: "second-brain" },
    {
      headers: {
        "Cache-Control": "no-store",
        "X-G2-Service": "second-brain",
      },
    },
  );
}
