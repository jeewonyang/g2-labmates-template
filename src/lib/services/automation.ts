import { spawn } from "child_process";
import { promises as fs } from "fs";
import path from "path";
import { db } from "@/lib/db";

const REPO = process.cwd();
const PYTHON =
  process.env.SECONDBRAIN_PYTHON || "python";
const CAPTURE_INBOX = path.join(
  REPO,
  "VAULT",
  "Research-Private",
  "00_Inbox",
  "G2-Captures",
);

function json(value: unknown): string {
  return JSON.stringify(value);
}

function safeDatePart(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function stagedRelativePath(item: { id: string; capturedAt: Date }): string {
  const date = safeDatePart(item.capturedAt);
  return path.posix.join(
    "VAULT",
    "Research-Private",
    "00_Inbox",
    "G2-Captures",
    date.slice(0, 7),
    `${item.id}.md`,
  );
}

function renderCapture(item: {
  id: string;
  rawText: string;
  parsedTitle: string | null;
  type: string;
  source: string;
  sourceUrl: string | null;
  dueDate: Date | null;
  capturedAt: Date;
  projectId: string | null;
  areaId: string | null;
}): string {
  const title = item.parsedTitle?.trim() || "Untitled capture";
  return [
    "---",
    "type: g2-capture",
    `g2_capture_id: ${JSON.stringify(item.id)}`,
    `capture_type: ${JSON.stringify(item.type)}`,
    `source: ${JSON.stringify(item.source)}`,
    `captured_at: ${JSON.stringify(item.capturedAt.toISOString())}`,
    `source_url: ${JSON.stringify(item.sourceUrl ?? "")}`,
    `due_date: ${JSON.stringify(item.dueDate?.toISOString() ?? "")}`,
    `project_id: ${JSON.stringify(item.projectId ?? "")}`,
    `area_id: ${JSON.stringify(item.areaId ?? "")}`,
    "---",
    "",
    `# ${title.replace(/\r?\n/g, " ")}`,
    "",
    item.rawText,
    "",
  ].join("\n");
}

async function stageCapture(item: Parameters<typeof renderCapture>[0]): Promise<string> {
  const rel = stagedRelativePath(item);
  const abs = path.join(REPO, ...rel.split("/"));
  await fs.mkdir(path.dirname(abs), { recursive: true });

  try {
    await fs.access(abs);
    return rel;
  } catch {
    // Continue with an atomic first write. Retried captures reuse the same path.
  }

  const tmp = `${abs}.${process.pid}.tmp`;
  await fs.writeFile(tmp, renderCapture(item), { encoding: "utf-8", flag: "wx" });
  try {
    await fs.rename(tmp, abs);
  } catch (error) {
    // Another request may have won the race. Preserve its durable file and
    // leave our temporary file in place rather than deleting user data.
    try {
      await fs.access(abs);
      return rel;
    } catch {
      throw error;
    }
  }
  return rel;
}

function runPython(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON, args, {
      cwd: REPO,
      windowsHide: true,
      env: { ...process.env, CLAUDE_INVOKED_BY: "capture-automation" },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => (stdout += String(chunk)));
    child.stderr.on("data", (chunk) => (stderr += String(chunk)));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve(stdout.trim());
      else reject(new Error((stderr || stdout || `Python exited ${code}`).trim()));
    });
  });
}

async function enqueueLocalTriage(payload: Record<string, unknown>): Promise<string> {
  const out = await runPython([
    ".claude/scripts/ledger.py",
    "create",
    "triage.classify",
    JSON.stringify(payload),
    "--runtime",
    "ollama",
    "--sensitivity",
    "private",
  ]);
  const id = out.split(/\r?\n/).filter(Boolean).at(-1);
  if (!id || !/^\d{13,19}-[0-9a-f]{8}$/.test(id)) {
    throw new Error(`Ledger returned an invalid job id: ${out.slice(0, 160)}`);
  }
  return id;
}

function startCycle(jobId: string): void {
  const child = spawn(
    PYTHON,
    [
      ".claude/scripts/automation_cycle.py",
      "--capture-job",
      jobId,
    ],
    {
      cwd: REPO,
      detached: true,
      stdio: "ignore",
      windowsHide: true,
      env: { ...process.env, CLAUDE_INVOKED_BY: "capture-automation" },
    },
  );
  child.unref();
}

export function startVaultAutomationCycle(): void {
  const child = spawn(
    PYTHON,
    [".claude/scripts/agent_day.py", "--team", "vault", "--force"],
    {
      cwd: REPO,
      detached: true,
      stdio: "ignore",
      windowsHide: true,
      env: { ...process.env, CLAUDE_INVOKED_BY: "dashboard-automation" },
    },
  );
  child.unref();
}

export async function queueCaptureAutomation(inboxItemId: string) {
  const row = await db.captureAutomation.findUnique({
    where: { inboxItemId },
    include: { inboxItem: true },
  });
  if (!row) throw new Error(`Automation record missing for inbox item ${inboxItemId}`);
  if (row.mode === "manual" || row.state === "applied" || row.state === "overridden") {
    return row;
  }
  if (row.localJobId && ["queued", "local_triage", "verifying", "ready"].includes(row.state)) {
    return row;
  }

  try {
    const stagedPath = await stageCapture(row.inboxItem);
    const jobId = await enqueueLocalTriage({
      path: stagedPath,
      inboxItemId: row.inboxItemId,
      automationId: row.id,
      source: "g2-capture",
    });
    const updated = await db.captureAutomation.update({
      where: { id: row.id },
      data: {
        state: "local_triage",
        stagedPath,
        localJobId: jobId,
        error: null,
        startedAt: row.startedAt ?? new Date(),
        events: {
          create: {
            type: "local_triage_queued",
            actor: "g2-capture",
            payload: json({ jobId, stagedPath }),
          },
        },
      },
    });
    startCycle(jobId);
    return updated;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await db.captureAutomation.update({
      where: { id: row.id },
      data: {
        state: "failed",
        error: message.slice(0, 2000),
        events: {
          create: {
            type: "failed",
            actor: "g2-capture",
            payload: json({ stage: "queue", error: message.slice(0, 1000) }),
          },
        },
      },
    });
    throw error;
  }
}

export async function retryCaptureAutomation(inboxItemId: string) {
  const row = await db.captureAutomation.findUnique({ where: { inboxItemId } });
  if (!row) throw new Error("This inbox item has no automation record.");
  if (row.state === "applied") return row;
  await db.captureAutomation.update({
    where: { id: row.id },
    data: {
      state: "queued",
      localJobId: null,
      verifierJobId: null,
      error: null,
      requiresReview: false,
      events: {
        create: { type: "retry_requested", actor: "owner" },
      },
    },
  });
  return queueCaptureAutomation(inboxItemId);
}

export async function markAutomationOverridden(
  inboxItemId: string,
  payload: Record<string, unknown>,
) {
  const row = await db.captureAutomation.findUnique({ where: { inboxItemId } });
  if (!row || row.state === "applied") return;
  await db.captureAutomation.update({
    where: { id: row.id },
    data: {
      state: "overridden",
      mode: "manual",
      completedAt: new Date(),
      events: {
        create: {
          type: "manual_override",
          actor: "owner",
          payload: json(payload),
        },
      },
    },
  });
}

export type CaptureCorrection = {
  kind: "task" | "note" | "resource";
  title: string;
  details?: string;
  context?: string | null;
  dueDate?: string | null;
  priority?: "low" | "medium" | "high" | "urgent";
};

const CORRECTION_KINDS = new Set(["task", "note", "resource"]);
const CORRECTION_CONTEXTS = new Set([
  "office", "lab", "computer", "phone", "home", "errand",
  "anywhere", "creative", "routine",
]);
const CORRECTION_PRIORITIES = new Set(["low", "medium", "high", "urgent"]);

/**
 * Decline-and-edit for a capture the agent already filed.
 *
 * Most captures are auto-approved by the two-tier verifier, so by the time you
 * see a misclassification the Task/Note/Resource already exists. The
 * Python side soft-archives the wrong entity, repoints the InboxItem, appends
 * provenance, and records the correction as a learned tendency — it never
 * deletes. Node validates and shells out; it never writes Prisma here, so the
 * archive-plus-relink transaction has exactly one implementation.
 */
export async function correctAppliedCapture(
  inboxItemId: string,
  correction: CaptureCorrection,
) {
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(inboxItemId)) {
    throw new Error("Invalid inbox item id.");
  }
  if (!CORRECTION_KINDS.has(correction.kind)) {
    throw new Error("Correction must be a task, note, or resource.");
  }
  const title = String(correction.title ?? "").trim().slice(0, 300);
  if (!title) throw new Error("A corrected item needs a title.");
  const dueDate =
    correction.kind === "task" &&
    typeof correction.dueDate === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(correction.dueDate)
      ? correction.dueDate
      : null;
  const context =
    correction.kind === "task" &&
    typeof correction.context === "string" &&
    CORRECTION_CONTEXTS.has(correction.context)
      ? correction.context
      : null;
  const priority = CORRECTION_PRIORITIES.has(String(correction.priority ?? ""))
    ? String(correction.priority)
    : "medium";

  const action = {
    kind: correction.kind,
    title,
    details: String(correction.details ?? "").slice(0, 10000),
    priority,
    context,
    due_date: dueDate,
    scheduled_date: null,
    duration_minutes: null,
    calendar_event: false,
    project: null,
    area: null,
    confidence: 1,
  };

  const out = await runPython([
    ".claude/scripts/capture_sync.py",
    "correct",
    inboxItemId,
    JSON.stringify(action),
    "--by",
    "owner",
  ]);
  try {
    return JSON.parse(out.split(/\r?\n/).filter(Boolean).at(-1) ?? "{}");
  } catch {
    return { corrected: true };
  }
}

/** Captures the agent filed on its own, newest first — the decline surface. */
export async function listOrganizedCaptures(limit = 12) {
  const rows = await db.captureAutomation.findMany({
    where: { state: "applied" },
    orderBy: { completedAt: "desc" },
    take: Math.max(1, Math.min(limit, 50)),
    include: {
      inboxItem: {
        select: {
          id: true,
          rawText: true,
          parsedTitle: true,
          capturedAt: true,
          processedIntoType: true,
          processedIntoId: true,
        },
      },
    },
  });
  return rows.map((row) => ({
    inboxItemId: row.inboxItemId,
    title: row.inboxItem.parsedTitle ?? row.inboxItem.rawText.slice(0, 120),
    rawText: row.inboxItem.rawText,
    filedAs: row.inboxItem.processedIntoType,
    destinationPath: row.destinationPath,
    confidence: row.confidence,
    completedAt: row.completedAt ?? row.updatedAt,
  }));
}

/**
 * Recent window for the Today panel's finished-work counts.
 *
 * `applied` and `overridden` are terminal and nothing ever clears them, so an
 * unbounded count is a lifetime odometer: it only rises and answers no question
 * you can act on. Unresolved states (queued/verifying/needs_review/failed) are
 * NOT windowed — a capture stuck for three weeks still needs you, and hiding it
 * once it ages out would be the one genuinely dangerous version of this.
 */
const RECENT_WINDOW_DAYS = 7;

export async function getAutomationDashboard() {
  const since = new Date(Date.now() - RECENT_WINDOW_DAYS * 24 * 60 * 60 * 1000);
  const [byState, recent, events] = await Promise.all([
    db.captureAutomation.groupBy({
      by: ["state"],
      _count: { _all: true },
    }),
    db.captureAutomation.findMany({
      // Anything unresolved, plus finished work from the last week.
      where: {
        OR: [
          { state: { in: ["queued", "local_triage", "verifying", "ready", "needs_review", "failed"] } },
          { updatedAt: { gte: since } },
        ],
      },
      orderBy: { updatedAt: "desc" },
      take: 8,
      include: {
        inboxItem: {
          select: { id: true, parsedTitle: true, rawText: true, capturedAt: true },
        },
      },
    }),
    db.automationEvent.findMany({
      orderBy: { createdAt: "desc" },
      take: 12,
    }),
  ]);
  const counts = Object.fromEntries(byState.map((row) => [row.state, row._count._all]));
  const appliedRecently = await db.captureAutomation.count({
    where: { state: "applied", updatedAt: { gte: since } },
  });
  return {
    counts,
    recent,
    events,
    appliedRecently,
    recentWindowDays: RECENT_WINDOW_DAYS,
    active:
      (counts.queued ?? 0) +
      (counts.local_triage ?? 0) +
      (counts.verifying ?? 0) +
      (counts.ready ?? 0),
    needsAttention: (counts.needs_review ?? 0) + (counts.failed ?? 0),
  };
}

export async function getAutomationForInbox(inboxItemId: string) {
  return db.captureAutomation.findUnique({
    where: { inboxItemId },
    include: { events: { orderBy: { createdAt: "desc" }, take: 10 } },
  });
}

// Exported for tests and diagnostics.
export const automationPaths = { captureInbox: CAPTURE_INBOX };
