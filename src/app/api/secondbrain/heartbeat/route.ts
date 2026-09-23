import { NextResponse } from "next/server";
import { spawn } from "child_process";
import { authorizeOps } from "@/lib/auth";

/**
 * POST /api/secondbrain/heartbeat — run the Admin team on demand.
 * Scans Gmail plus read-state-independent Slack DMs, then drains reply jobs.
 * Advisor mode: drafts + notifies, never sends.
 */

const REPO = process.cwd();
const PYTHON = process.env.SECONDBRAIN_PYTHON ||
  "python";

export const maxDuration = 600; // a complete Slack DM sweep can be rate-limited

export async function POST(request: Request) {
  const auth = authorizeOps(request);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.message }, { status: auth.status });
  }

  const result = await new Promise<{ code: number; out: string }>((resolve) => {
    const p = spawn(
      PYTHON,
      [".claude/scripts/agent_day.py", "--team", "admin", "--force"],
      { cwd: REPO },
    );
    let out = "";
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (out += d));
    p.on("close", (code) => resolve({ code: code ?? -1, out: out.trim() }));
    p.on("error", (e) => resolve({ code: -1, out: String(e) }));
  });

  if (result.code !== 0) {
    const runtimeUnavailable = /\bENOENT\b|\bspawn\b/i.test(result.out);
    return NextResponse.json(
      {
        error: "admin scan failed",
        detail: runtimeUnavailable
          ? "The local agent runtime is unavailable. Check SECONDBRAIN_PYTHON and try again."
          : "The scan did not complete. Check the local heartbeat log and try again.",
      },
      { status: 502 }
    );
  }
  return NextResponse.json({ ok: true, message: result.out.slice(-400) || "Scan complete." });
}
