import { NextResponse } from "next/server";
import { spawn } from "child_process";
import { authorizeOps } from "@/lib/auth";
import { getJob, type TriageProposal } from "@/lib/services/ledger";

/**
 * POST /api/ops — act on Agent OS jobs.
 *   { action: "approve", jobIds: [...] }
 *   { action: "reject",  jobIds: [...], reason }
 *   { action: "cancel",  jobIds: [...], reason }
 *   { action: "reap" }
 *
 * Every mutation shells out to .claude/scripts/ledger.py so the state machine
 * has exactly one implementation. Node never writes the ledger or the vault.
 *
 * Security: gated by authorizeOps (the dashboard is tailnet-reachable, and
 * approving a job files documents into the vault). Job ids are validated
 * against a strict pattern before they reach a subprocess argument — the same
 * class of hole the draft route's safeName guard exists for.
 */

const REPO = process.cwd();
const PYTHON =
  process.env.SECONDBRAIN_PYTHON || "python";

/** ledger.py ids are `<16-digit microseconds>-<8 hex>`. Nothing else is valid. */
const JOB_ID = /^\d{13,19}-[0-9a-f]{8}$/;

const MAX_BATCH = 500;

function runLedger(args: string[]): Promise<{ ok: boolean; out: string }> {
  return new Promise((resolve) => {
    const p = spawn(PYTHON, [".claude/scripts/ledger.py", ...args], { cwd: REPO });
    let out = "";
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (out += d));
    p.on("close", (code) => resolve({ ok: code === 0, out: out.trim() }));
    p.on("error", (e) => resolve({ ok: false, out: String(e) }));
  });
}

function runReview(args: string[]): Promise<{ ok: boolean; out: string }> {
  return new Promise((resolve) => {
    const p = spawn(
      PYTHON,
      [".claude/scripts/triage/review.py", ...args],
      { cwd: REPO, windowsHide: true },
    );
    let out = "";
    p.stdout.on("data", (d) => (out += d));
    p.stderr.on("data", (d) => (out += d));
    p.on("close", (code) => resolve({ ok: code === 0, out: out.trim() }));
    p.on("error", (e) => resolve({ ok: false, out: String(e) }));
  });
}

function safeFolder(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const normalized = value.trim().replaceAll("\\", "/");
  const parts = normalized.split("/");
  const reserved = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i;
  if (
    normalized.startsWith("/") ||
    /^[A-Za-z]:/.test(normalized) ||
    parts.length > 2 ||
    parts.some(
      (part) =>
        !part ||
        part === "." ||
        part === ".." ||
        part.length > 80 ||
        /[<>:"|?*\u0000-\u001f]/.test(part) ||
        /[ .]$/.test(part) ||
        reserved.test(part) ||
        ["finance", "_private"].includes(part.toLowerCase()),
    )
  ) {
    return null;
  }
  return parts.join("/");
}

function safeActions(value: unknown): TriageProposal["actions"] {
  if (!Array.isArray(value)) return [];
  const kinds = new Set(["task", "note", "resource", "none"]);
  const priorities = new Set(["low", "medium", "high", "urgent"]);
  const contexts = new Set([
    "office", "lab", "computer", "phone", "home", "errand",
    "anywhere", "creative", "routine",
  ]);
  return value.slice(0, 10).flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return [];
    const action = entry as Record<string, unknown>;
    const kind = String(action.kind ?? "");
    if (!kinds.has(kind)) return [];
    const due = typeof action.due_date === "string" &&
      /^\d{4}-\d{2}-\d{2}$/.test(action.due_date)
      ? action.due_date
      : null;
    const scheduled = typeof action.scheduled_date === "string" &&
      /^\d{4}-\d{2}-\d{2}T/.test(action.scheduled_date)
      ? action.scheduled_date.slice(0, 40)
      : null;
    const context = typeof action.context === "string" &&
      contexts.has(action.context)
      ? action.context
      : null;
    const priority = priorities.has(String(action.priority ?? ""))
      ? String(action.priority)
      : "medium";
    return [{
      kind: kind as "task" | "note" | "resource" | "none",
      title: String(action.title ?? "").trim().slice(0, 300),
      details: String(action.details ?? "").slice(0, 10000),
      priority: priority as "low" | "medium" | "high" | "urgent",
      context,
      due_date: due,
      scheduled_date: scheduled,
      duration_minutes:
        typeof action.duration_minutes === "number" &&
        Number.isFinite(action.duration_minutes) &&
        action.duration_minutes > 0
          ? Math.min(action.duration_minutes, 1440)
          : null,
      calendar_event: Boolean(action.calendar_event && scheduled),
      project:
        typeof action.project === "string"
          ? action.project.trim().slice(0, 120) || null
          : null,
      area:
        typeof action.area === "string"
          ? action.area.trim().slice(0, 120) || null
          : null,
      confidence:
        typeof action.confidence === "number" && Number.isFinite(action.confidence)
          ? Math.max(0, Math.min(1, action.confidence))
          : 1,
    }];
  });
}

function runCaptureCycle(jobId: string): void {
  const child = spawn(
    PYTHON,
    [".claude/scripts/automation_cycle.py", "--capture-job", jobId],
    {
      cwd: REPO,
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    },
  );
  child.unref();
}

/**
 * File everything currently approved, out-of-band.
 *
 * Detached and unawaited on purpose. Approving is a decision and must feel
 * instant — approving 489 files is two clicks, copying them is slow I/O that
 * would time out this request. So the response returns on the ledger
 * transition alone and the effect lands seconds later.
 *
 * Safe to fire per-request: apply_jobs.py serializes on APPLY_LOCK and reads
 * the approved queue only after acquiring it, so overlapping spawns file each
 * job exactly once. If the spawn fails outright the job stays `approved` and
 * Agent Day's drain files it — the pre-automation behaviour.
 */
function runApplyJobs(): void {
  const child = spawn(PYTHON, [".claude/scripts/apply_jobs.py", "--max", "200"], {
    cwd: REPO,
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  child.on("error", () => {});
  child.unref();
}

/**
 * Run the dispatcher over whatever is queued, right now.
 *
 * This does NOT widen Advisor mode. The dispatcher claims and runs jobs; any
 * job whose effect reaches outside VAULT/Memory/ still lands in `needs_review`
 * and waits for an explicit approval, which is a separate action on this same
 * route. What the button removes is only the wait for the next scheduled run.
 *
 * Detached and unawaited for the same reason as apply: a drain can take
 * minutes and would time out the request. `--max` bounds one press so a click
 * cannot kick off an unbounded run, and the ledger's atomic claim makes a
 * second press while one is in flight a no-op rather than a double-run.
 */
function runDispatcher(): void {
  const child = spawn(
    PYTHON,
    [".claude/scripts/dispatch.py", "--once", "--max", "25"],
    { cwd: REPO, detached: true, stdio: "ignore", windowsHide: true },
  );
  child.on("error", () => {});
  child.unref();
}

export async function POST(req: Request) {
  const auth = authorizeOps(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.message }, { status: auth.status });
  }

  const body = await req.json().catch(() => ({}));
  const { action, jobIds, reason, proposal } = body as {
    action?: string;
    jobIds?: unknown;
    reason?: unknown;
    proposal?: unknown;
  };

  if (action === "reap") {
    const { ok, out } = await runLedger(["reap"]);
    return ok
      ? NextResponse.json({ ok: true, message: out })
      : NextResponse.json({ error: out }, { status: 500 });
  }

  // "Run queued work now" — the dispatcher only. Approval stays a separate
  // action; a drain can create review items but can never clear them.
  if (action === "drain") {
    runDispatcher();
    return NextResponse.json(
      { ok: true, message: "Running queued work in the background." },
      { status: 202 },
    );
  }

  if (
    action !== "approve" &&
    action !== "reject" &&
    action !== "revise" &&
    action !== "cancel" &&
    action !== "resolve"
  ) {
    return NextResponse.json({ error: "unknown action" }, { status: 400 });
  }

  if (!Array.isArray(jobIds) || jobIds.length === 0) {
    return NextResponse.json({ error: "jobIds must be a non-empty array" }, { status: 400 });
  }
  if (jobIds.length > MAX_BATCH) {
    return NextResponse.json(
      { error: `batch too large (max ${MAX_BATCH})` },
      { status: 400 },
    );
  }
  // Validate every id BEFORE any subprocess runs, so one bad id rejects the
  // whole request rather than half-applying it.
  const ids: string[] = [];
  for (const id of jobIds) {
    if (typeof id !== "string" || !JOB_ID.test(id)) {
      return NextResponse.json({ error: `invalid job id: ${String(id).slice(0, 40)}` }, { status: 400 });
    }
    ids.push(id);
  }

  const why =
    typeof reason === "string" && reason.trim()
      ? reason.trim().slice(0, 300)
      : action === "cancel"
        ? "no longer needed"
        : action === "resolve"
          ? "acknowledged from /ops"
          : "rejected from /ops";

  let revisedProposal: Record<string, unknown> | null = null;
  if (action === "revise") {
    if (ids.length !== 1 || !proposal || typeof proposal !== "object" || Array.isArray(proposal)) {
      return NextResponse.json(
        { error: "revise requires exactly one job and one proposal object" },
        { status: 400 },
      );
    }
    const candidate = proposal as Record<string, unknown>;
    const vaults = new Set([
      "G2OS-Staging",
      "Research-Private",
      "Confidential",
      "Finance",
      "leave-in-inbox",
    ]);
    const buckets: Record<string, Set<string>> = {
      "G2OS-Staging": new Set(["10_Projects", "20_Areas", "30_Resources", "90_Archive"]),
      "Research-Private": new Set(["10_Projects", "20_Areas", "30_Resources", "90_Archive"]),
      Confidential: new Set(["20_Areas", "40_People", "90_Archive"]),
      Finance: new Set(["20_Areas", "30_Resources", "90_Archive"]),
      "leave-in-inbox": new Set(["none"]),
    };
    const vault = String(candidate.vault ?? "");
    const bucket = String(candidate.bucket ?? "");
    if (!vaults.has(vault) || !buckets[vault]?.has(bucket)) {
      return NextResponse.json({ error: "invalid vault/bucket combination" }, { status: 422 });
    }
    let requestedFolder = safeFolder(candidate.folder ?? candidate.project);
    let folderMode = String(
      candidate.folder_mode ?? (requestedFolder ? "existing" : "bucket-root"),
    );
    if (vault === "leave-in-inbox") {
      requestedFolder = null;
      folderMode = "bucket-root";
    }
    if (!["bucket-root", "existing", "create"].includes(folderMode)) {
      return NextResponse.json({ error: "invalid folder mode" }, { status: 422 });
    }
    if (folderMode !== "bucket-root" && !requestedFolder) {
      return NextResponse.json(
        { error: "existing/create folder mode requires a safe relative folder" },
        { status: 422 },
      );
    }
    if (
      vault !== "leave-in-inbox" &&
      folderMode === "bucket-root" &&
      candidate.folder
    ) {
      return NextResponse.json(
        { error: "bucket-root mode cannot include a folder" },
        { status: 422 },
      );
    }
    if (bucket === "10_Projects" && folderMode === "bucket-root") {
      return NextResponse.json(
        { error: "10_Projects requires a project folder" },
        { status: 422 },
      );
    }
    const project =
      bucket === "10_Projects"
        ? safeFolder(candidate.project ?? requestedFolder?.split("/")[0])
        : null;
    if (bucket === "10_Projects" && (!project || project.includes("/"))) {
      return NextResponse.json(
        { error: "10_Projects requires a safe single-folder project name" },
        { status: 422 },
      );
    }
    revisedProposal = {
      ...candidate,
      vault,
      bucket,
      project,
      folder: folderMode === "bucket-root" ? null : requestedFolder,
      folder_mode: folderMode,
      folder_rationale: String(
        candidate.folder_rationale ?? "Corrected manually in G2",
      ).slice(0, 500),
      reason: String(candidate.reason ?? "Corrected manually in G2").slice(0, 500),
      actions: safeActions(candidate.actions),
    };
  }

  const results: { job: string; ok: boolean; message: string }[] = [];
  let approvedAny = false;
  for (const id of ids) {
    const current = action === "approve" ? await getJob(id) : null;
    const currentProposal = (current?.proposal ?? {}) as TriageProposal;
    if (action === "approve" && currentProposal.folder_mode === "create") {
      const { ok, out } = await runReview([
        "prepare-folder",
        id,
        "--by",
        "owner",
      ]);
      if (ok) {
        try {
          const prepared = JSON.parse(out) as { reclassificationJobId?: string };
          const payload =
            typeof current?.payload === "object" && current.payload !== null
              ? (current.payload as { automationId?: string })
              : {};
          if (prepared.reclassificationJobId && payload.automationId) {
            runCaptureCycle(prepared.reclassificationJobId);
          }
        } catch {
          // The durable ledger job still exists; the scheduled cycle will run it.
        }
      }
      results.push({ job: id, ok, message: out });
      continue;
    }
    const args =
      action === "approve"
        ? // --no-apply: ledger.py's own CLI spawns an apply run per approve,
          // which would mean one Python process per job in a 489-file batch.
          // This route spawns exactly one for the whole batch instead.
          ["approve", id, "--by", "owner", "--no-apply"]
        : action === "reject"
          ? ["reject", id, why, "--by", "owner"]
          : action === "cancel"
            ? ["cancel", id, "--reason", why, "--by", "owner"]
          : // Acknowledging a dead failure, using the ledger transition that
            // already exists for it (failed -> resolved). Nothing is deleted:
            // the failure and its error text stay in the append-only history,
            // they just stop occupying the panel. ledger.py refuses the
            // transition from any status other than `failed`, so this cannot
            // be pointed at live work.
            action === "resolve"
          ? ["resolve", id, "--by", "owner", "--note", why]
          : [
              "revise",
              id,
              JSON.stringify(revisedProposal),
              "--by",
              "owner",
              "--verdict",
              "manual",
            ];
    const { ok, out } = await runLedger(args);
    if (ok && action === "approve") approvedAny = true;
    results.push({ job: id, ok, message: out });
  }

  // One spawn for the whole batch, after every transition is recorded — not one
  // per job. apply_jobs.py drains the entire approved queue in a single locked
  // pass, so N spawns would only queue N-1 no-ops behind the lock.
  //
  // The folder_mode === "create" branch above never reaches here: it `continue`s
  // without approving, because creating a taxonomy folder supersedes the
  // classification and enqueues a fresh pass instead of producing an effect.
  if (approvedAny) runApplyJobs();

  const failed = results.filter((r) => !r.ok);
  return NextResponse.json(
    { ok: failed.length === 0, applied: results.length - failed.length, failed, results },
    { status: failed.length === 0 ? 200 : 207 },
  );
}
