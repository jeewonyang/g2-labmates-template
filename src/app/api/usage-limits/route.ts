import { NextResponse } from "next/server";
import { getUsageLimits } from "@/lib/services/limits";

/**
 * GET /api/usage-limits        — current Claude + Codex subscription limits
 * GET /api/usage-limits?force=1 — re-read them even if the cache is fresh
 *
 * Read-only and returns no credentials: the underlying script emits only
 * percentages, window labels, and reset timestamps.
 */

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const force = new URL(req.url).searchParams.get("force") === "1";
  const limits = await getUsageLimits(force);
  return NextResponse.json(limits, {
    headers: { "Cache-Control": "no-store" },
  });
}
