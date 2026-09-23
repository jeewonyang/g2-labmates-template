import { NextResponse } from "next/server";
import {
  getActivitySeenAt,
  listAgentActivity,
  markActivitySeen,
} from "@/lib/services/activity";
import { authorizeOps } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const raw = url.searchParams.get("since");
  const stored = raw ? null : await getActivitySeenAt();
  const parsed = raw
    ? new Date(raw)
    : stored ?? new Date(Date.now() - 24 * 60 * 60 * 1000);
  const since = Number.isFinite(parsed.getTime())
    ? parsed
    : new Date(Date.now() - 24 * 60 * 60 * 1000);
  const items = await listAgentActivity(since);
  return NextResponse.json({
    since: since.toISOString(),
    checkedAt: new Date().toISOString(),
    count: items.length,
    items,
  });
}

export async function POST(req: Request) {
  const auth = authorizeOps(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.message }, { status: auth.status });
  }
  const body = await req.json().catch(() => ({}));
  if (body.action !== "mark-seen") {
    return NextResponse.json({ error: "unknown action" }, { status: 400 });
  }
  const seen = await markActivitySeen();
  return NextResponse.json({ ok: true, seenAt: seen.toISOString() });
}
