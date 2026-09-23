import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import os from "os";
import { spawn } from "child_process";
import { authorizeOps } from "@/lib/auth";

/**
 * POST /api/secondbrain/draft — act on a vault reply draft (Advisor mode).
 *   { filename, action: "approve" }  -> push it into Gmail Drafts (never sends)
 *   { filename, action: "dismiss" }  -> archive it in drafts/expired/
 *   { filename, action: "classify", relationshipGroup } -> confirm the category
 *   { filename, action: "edit", reply } -> save and learn from a tone edit
 *   { action: "dismiss_all" } -> archive every active draft (never hard-delete)
 * Same-origin only (called by the app's own /drafts page).
 */

const REPO = process.cwd();
const ACTIVE = path.join(REPO, "VAULT", "Memory", "drafts", "active");
const PYTHON = process.env.SECONDBRAIN_PYTHON ||
  "python";

function field(raw: string, key: string): string {
  return raw.match(new RegExp(`^${key}:\\s*(.+)$`, "m"))?.[1].trim().replace(/^["']|["']$/g, "") ?? "";
}
function section(raw: string, heading: string): string {
  return raw.match(new RegExp(`##\\s+${heading}\\s*\\r?\\n([\\s\\S]*?)(?=\\r?\\n##\\s|$)`, "i"))?.[1].trim() ?? "";
}

function safeName(filename: string): string | null {
  // no path separators / traversal
  return /^[\w.\- ]+\.md$/.test(filename) ? filename : null;
}

function runQuery(args: string[]): Promise<{ ok: boolean; out: string }> {
  return new Promise((resolve) => {
    const p = spawn(PYTHON, [".claude/scripts/query.py", ...args], { cwd: REPO });
    let out = "";
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (out += d));
    p.on("close", (code) => resolve({ ok: code === 0, out: out.trim() }));
    p.on("error", (e) => resolve({ ok: false, out: String(e) }));
  });
}

function runFeedback(args: string[]): Promise<{ ok: boolean; out: string }> {
  return new Promise((resolve) => {
    const process = spawn(
      PYTHON,
      [".claude/scripts/draft_feedback.py", ...args],
      { cwd: REPO, windowsHide: true },
    );
    let out = "";
    process.stdout.on("data", (data) => (out += data));
    process.stderr.on("data", (data) => (out += data));
    process.on("close", (code) =>
      resolve({ ok: code === 0, out: out.trim() }),
    );
    process.on("error", (error) =>
      resolve({ ok: false, out: String(error) }),
    );
  });
}

export async function POST(req: Request) {
  const auth = authorizeOps(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.message }, { status: auth.status });
  }

  const { filename, action, relationshipGroup, reply } =
    await req.json().catch(() => ({}));
  const name = typeof filename === "string" ? safeName(filename) : null;
  if (action === "dismiss_all") {
    const { ok, out } = await runFeedback(["dismiss-all"]);
    let result: {
      archived?: number;
      failed?: Array<{ filename: string; error: string }>;
    } = {};
    try {
      result = JSON.parse(out.split(/\r?\n/).filter(Boolean).at(-1) ?? "{}");
    } catch {
      // Keep the subprocess output as the useful fallback error below.
    }
    const failed = result.failed ?? [];
    return NextResponse.json(
      {
        ok: ok && failed.length === 0,
        archived: result.archived ?? 0,
        failed,
        message:
          failed.length > 0
            ? `Archived ${result.archived ?? 0}; ${failed.length} could not be archived.`
            : `Archived ${result.archived ?? 0} active draft(s).`,
        ...(!ok && failed.length === 0
          ? { error: out || "bulk dismissal failed" }
          : {}),
      },
      { status: ok ? 200 : failed.length > 0 ? 207 : 500 },
    );
  }
  if (
    !name ||
    !["approve", "dismiss", "classify", "edit"].includes(String(action))
  ) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }
  const src = path.join(ACTIVE, name);
  const raw = await fs.readFile(src, "utf-8").catch(() => null);
  if (!raw) return NextResponse.json({ error: "draft not found" }, { status: 404 });

  if (action === "dismiss") {
    const { ok, out } = await runFeedback(["dismiss", name]);
    return ok
      ? NextResponse.json({ ok: true, moved: "expired", message: out })
      : NextResponse.json({ error: out || "dismissal failed" }, { status: 500 });
  }

  if (action === "classify") {
    const groups = new Set([
      "Mentor/PI",
      "Mentee",
      "Collaborator",
      "Colleague",
    ]);
    if (typeof relationshipGroup !== "string" || !groups.has(relationshipGroup)) {
      return NextResponse.json(
        { error: "invalid relationship category" },
        { status: 422 },
      );
    }
    const { ok, out } = await runFeedback([
      "classify",
      name,
      relationshipGroup,
    ]);
    return ok
      ? NextResponse.json({ ok: true, message: out })
      : NextResponse.json(
          { error: out || "classification update failed" },
          { status: 500 },
        );
  }

  if (action === "edit") {
    if (typeof reply !== "string" || !reply.trim() || reply.length > 20_000) {
      return NextResponse.json(
        { error: "reply must contain 1-20,000 characters" },
        { status: 422 },
      );
    }
    const tmp = path.join(os.tmpdir(), `sb-draft-edit-${Date.now()}.txt`);
    await fs.writeFile(tmp, reply.trim(), "utf-8");
    const result = await runFeedback(["edit", name, "--reply-file", tmp]);
    await fs.unlink(tmp).catch(() => {});
    return result.ok
      ? NextResponse.json({ ok: true, learned: true, message: result.out })
      : NextResponse.json(
          { error: result.out || "reply edit failed" },
          { status: 500 },
        );
  }

  // approve -> create a Gmail draft from the reply body
  if (field(raw, "type").toLowerCase() === "slack") {
    return NextResponse.json(
      {
        error:
          "Slack is read-only. Copy the reply from /drafts and post it manually.",
      },
      { status: 409 },
    );
  }
  const to = field(raw, "recipient");
  const subject = field(raw, "subject");
  const body = section(raw, "Draft Reply");
  if (!to || !body) {
    return NextResponse.json({ error: "draft missing recipient or reply body" }, { status: 422 });
  }
  const tmp = path.join(os.tmpdir(), `sb-draft-${Date.now()}.txt`);
  await fs.writeFile(tmp, body, "utf-8");
  const { ok, out } = await runQuery(["gmail", "draft", to, subject, tmp]);
  await fs.unlink(tmp).catch(() => {});
  if (!ok) return NextResponse.json({ error: out || "draft creation failed" }, { status: 502 });
  return NextResponse.json({ ok: true, message: out });
}
