/**
 * Read-only view of the Agent OS job ledger.
 *
 * Mirrors the secondbrain.ts pattern: framework-free, filesystem only, no
 * Prisma, and it swallows errors and returns empty rather than throwing — a
 * missing ledger renders an empty state, never a 500.
 *
 * The ledger is append-only JSONL written by .claude/scripts/ledger.py. This
 * file only READS it. Every mutation goes through the Python CLI via
 * /api/ops, so the state machine has exactly one implementation.
 *
 * Fold semantics must match ledger.py::fold — insertion order is FIFO order,
 * and the snapshot caches a byte offset. If the two drift, this page lies;
 * `npm run test:ledger-parity` (see tests) compares both against the same log.
 */
import { readFileSync, statSync } from "fs";
import path from "path";

const REPO = process.cwd();
const LEDGER_DIR = path.join(REPO, ".claude", "data", "ledger");
const EVENTS = path.join(LEDGER_DIR, "events.jsonl");
const SNAPSHOT = path.join(LEDGER_DIR, "snapshot.json");

export type JobStatus =
  | "created" | "claimed" | "completed" | "failed"
  | "needs_review" | "approved" | "rejected" | "superseded" | "resolved"
  | "cancelled";

export interface Job {
  job: string;
  kind: string | null;
  payload: unknown;
  runtime: string | null;
  sensitivity: string;
  parent: string | null;
  status: JobStatus;
  created_ts?: string;
  updated_ts?: string;
  claimed_ts?: string;
  worker?: string | null;
  attempts?: number;
  result?: unknown;
  error?: string;
  retryable?: boolean;
  proposal?: TriageProposal | Record<string, unknown>;
  approved_by?: string;
  reject_reason?: string;
  reviewed_by?: string;
  review_verdict?: string;
  review_note?: string;
  replacement_job?: string;
  superseded_by?: string;
  resolved_by?: string;
  resolution_note?: string;
  cancelled_by?: string;
  cancel_reason?: string;
  /** Set by a `deferred` event: the job is queued but not claimable before this ISO time. */
  not_before?: string;
  defer_reason?: string;
  deferrals?: number;
  _consumed?: boolean;
}

export interface TriageProposal {
  vault?: string;
  bucket?: string;
  project?: string | null;
  folder?: string | null;
  folder_mode?: "bucket-root" | "existing" | "create";
  folder_rationale?: string;
  person?: string | null;
  confidence?: number;
  title?: string;
  reason?: string;
  actions?: TriageAction[];
}

export interface TriageAction {
  kind?: "task" | "note" | "resource" | "none";
  title?: string;
  details?: string;
  priority?: "low" | "medium" | "high" | "urgent";
  context?: string | null;
  due_date?: string | null;
  scheduled_date?: string | null;
  duration_minutes?: number | null;
  calendar_event?: boolean;
  project?: string | null;
  area?: string | null;
  confidence?: number;
}

export interface QueueStats {
  total: number;
  created: number;
  claimed: number;
  needsReview: number;
  failed: number;
  completed: number;
  completedToday: number;
  rejected: number;
  oldestPendingIso: string | null;
  staleClaims: number;
}

/** A claim older than this is presumed abandoned — matches ledger.py. */
const STALE_CLAIM_MS = 30 * 60 * 1000;

type EventRow = Record<string, unknown> & { job?: string; event?: string };

type FoldCache = {
  signature: string;
  jobs: Map<string, Job>;
};

let foldCache: FoldCache | null = null;

function fileSignature(file: string): string {
  try {
    const stat = statSync(file);
    return `${stat.size}:${stat.mtimeMs}`;
  } catch {
    return "missing";
  }
}

function applyEvent(jobs: Map<string, Job>, ev: EventRow): void {
  const jid = typeof ev.job === "string" ? ev.job : "";
  if (!jid) return;
  const ts = typeof ev.ts === "string" ? ev.ts : undefined;

  if (ev.event === "created") {
    jobs.set(jid, {
      job: jid,
      kind: (ev.kind as string) ?? null,
      payload: ev.payload,
      runtime: (ev.runtime as string) ?? null,
      sensitivity: (ev.sensitivity as string) ?? "private",
      parent: (ev.parent as string) ?? null,
      status: "created",
      created_ts: ts,
      updated_ts: ts,
      worker: null,
      attempts: 0,
    });
    return;
  }
  const job = jobs.get(jid);
  if (!job) return;
  job.updated_ts = ts;

  switch (ev.event) {
    case "claimed":
      job.status = "claimed";
      job.worker = (ev.worker as string) ?? null;
      job.claimed_ts = ts;
      job.attempts = (job.attempts ?? 0) + 1;
      delete job.not_before;
      break;
    case "released":
      job.status = "created";
      job.worker = null;
      delete job.claimed_ts;
      break;
    case "deferred":
      // Back in the queue until a subscription window resets. Mirrors
      // ledger.py: status is `created`, and claim() skips it while
      // not_before is in the future.
      job.status = "created";
      job.worker = null;
      delete job.claimed_ts;
      job.not_before = ev.not_before as string;
      job.defer_reason = ev.reason as string;
      job.deferrals = (job.deferrals ?? 0) + 1;
      break;
    case "completed":
      job.status = "completed";
      job.result = ev.result;
      break;
    case "failed":
      job.status = "failed";
      job.error = ev.error as string;
      job.retryable = ev.retryable !== false;
      break;
    case "cancelled":
      job.status = "cancelled";
      job.cancelled_by = ev.by as string;
      job.cancel_reason = ev.reason as string;
      break;
    case "needs_review":
      job.status = "needs_review";
      job.proposal = ev.proposal as TriageProposal;
      break;
    case "approved":
      job.status = "approved";
      job.approved_by = ev.by as string;
      break;
    case "rejected":
      job.status = "rejected";
      job.reject_reason = ev.reason as string;
      break;
    case "revised":
      // A revision updates the proposal while deliberately retaining
      // needs_review. This must mirror ledger.py or /ops displays stale model
      // output after the verifier corrects it.
      job.proposal = ev.proposal as TriageProposal;
      job.reviewed_by = ev.by as string;
      job.review_verdict = ev.verdict as string;
      job.review_note = ev.note as string;
      break;
    case "superseded":
      job.status = "superseded";
      job.replacement_job = ev.replacement as string;
      job.superseded_by = ev.by as string;
      break;
    case "consumed":
      job._consumed = true;
      break;
    case "resolved":
      job.status = "resolved";
      job.resolved_by = ev.by as string;
      job.resolution_note = ev.note as string;
      job.replacement_job = ev.replacement as string;
      break;
  }
}

/**
 * Fold the append-only ledger into current job state.
 *
 * Keep this path synchronous on purpose. React's development server records
 * values produced by awaited server-side I/O for its RSC debug payload. When
 * the 3 MB snapshot and event Buffer were read with fs.promises, those values
 * were serialized into every page response (twice on Home), inflating a
 * routine navigation to roughly 29 MB. The files are local and small enough
 * for a synchronous cold read, and the signature cache makes unchanged reads
 * effectively free.
 */
function fold(): Map<string, Job> {
  const signature = `${fileSignature(SNAPSHOT)}|${fileSignature(EVENTS)}`;
  if (foldCache?.signature === signature) return foldCache.jobs;

  const jobs = new Map<string, Job>();
  let offset = 0;

  try {
    const snap = JSON.parse(readFileSync(SNAPSHOT, "utf-8"));
    if (snap && typeof snap === "object") {
      offset = Number(snap.offset) || 0;
      for (const [k, v] of Object.entries(snap.jobs ?? {})) {
        jobs.set(k, v as Job);
      }
    }
  } catch {
    offset = 0;
    jobs.clear();
  }

  let raw: Buffer;
  try {
    raw = readFileSync(EVENTS);
  } catch {
    foldCache = { signature, jobs };
    return jobs; // no ledger yet
  }
  if (offset > raw.length) {
    jobs.clear();
    offset = 0; // rotated or truncated
  }

  const tail = raw.subarray(offset).toString("utf-8");
  for (const line of tail.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      applyEvent(jobs, JSON.parse(t));
    } catch {
      // partial trailing write, or a corrupt line: skip it
    }
  }
  foldCache = { signature, jobs };
  return jobs;
}

export async function listJobs(opts: {
  status?: JobStatus;
  kind?: string;
  limit?: number;
} = {}): Promise<Job[]> {
  const jobs = [...fold().values()];
  const filtered = jobs.filter(
    (j) =>
      (!opts.status || j.status === opts.status) &&
      (!opts.kind || j.kind === opts.kind),
  );
  return opts.limit ? filtered.slice(0, opts.limit) : filtered;
}

export async function getJob(id: string): Promise<Job | null> {
  return fold().get(id) ?? null;
}

export async function getQueueStats(): Promise<QueueStats> {
  const jobs = [...fold().values()];
  const count = (s: JobStatus) => jobs.filter((j) => j.status === s).length;

  const pending = jobs
    .filter((j) => j.status === "created")
    .map((j) => j.created_ts)
    .filter(Boolean)
    .sort();

  const now = Date.now();
  const staleClaims = jobs.filter((j) => {
    if (j.status !== "claimed") return false;
    const t = Date.parse(j.claimed_ts ?? j.updated_ts ?? "");
    return Number.isFinite(t) && now - t > STALE_CLAIM_MS;
  }).length;

  // Completions since local midnight. The lifetime total (1,100+ and only ever
  // rising) answered no question you could act on; "did the pipeline run today"
  // is one you can.
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  const completedToday = jobs.filter((j) => {
    if (j.status !== "completed") return false;
    const t = Date.parse(j.updated_ts ?? j.created_ts ?? "");
    return Number.isFinite(t) && t >= midnight.getTime();
  }).length;

  return {
    total: jobs.length,
    created: count("created"),
    claimed: count("claimed"),
    needsReview: count("needs_review"),
    failed: count("failed"),
    completed: count("completed"),
    completedToday,
    rejected: count("rejected"),
    oldestPendingIso: pending[0] ?? null,
    staleClaims,
  };
}

export interface ReviewBatch {
  key: string;
  vault: string;
  bucket: string;
  project: string | null;
  folder: string | null;
  folderMode: "bucket-root" | "existing" | "create";
  count: number;
  meanConfidence: number;
  /** Only ambiguous destinations and new projects require per-item handling. */
  requiresPerItem: boolean;
  jobs: Job[];
}

/**
 * Group needs_review jobs by proposed destination.
 *
 * This is what makes ~1,000 pending classifications reviewable: one decision
 * per destination instead of one per file. Confidential batches are flagged
 * requiresPerItem so the UI withholds bulk approval — the same rule the
 * classifier and taxonomy.md enforce.
 */
export async function listReviewBatches(): Promise<ReviewBatch[]> {
  // Destination batches are meaningful only for file classifications. Other
  // review-gated jobs (security findings, schedule proposals, etc.) have a
  // different proposal shape and must not be rendered as
  // "unclassified/none" files.
  const jobs = (await listJobs({ status: "needs_review" })).filter(
    (job) => job.kind === "triage.classify",
  );
  const groups = new Map<string, Job[]>();

  for (const j of jobs) {
    const p = (j.proposal ?? {}) as TriageProposal;
    const vault = p.vault ?? "unclassified";
    const bucket = p.bucket ?? "none";
    const project = p.project ?? null;
    const folder = p.folder ?? project;
    const folderMode = p.folder_mode ?? (folder ? "existing" : "bucket-root");
    const key = `${vault}/${bucket}${folder ? `/${folder}` : ""}${
      folderMode === "create" ? " [new folder]" : ""
    }`;
    const list = groups.get(key);
    if (list) list.push(j);
    else groups.set(key, [j]);
  }

  const batches: ReviewBatch[] = [];
  for (const [key, list] of groups) {
    const p = (list[0].proposal ?? {}) as TriageProposal;
    const confidences = list
      .map((j) => Number((j.proposal as TriageProposal)?.confidence))
      .filter((n) => Number.isFinite(n));
    batches.push({
      key,
      vault: p.vault ?? "unclassified",
      bucket: p.bucket ?? "none",
      project: p.project ?? null,
      folder: p.folder ?? p.project ?? null,
      folderMode:
        p.folder_mode ?? ((p.folder ?? p.project) ? "existing" : "bucket-root"),
      count: list.length,
      meanConfidence: confidences.length
        ? confidences.reduce((a, b) => a + b, 0) / confidences.length
        : 0,
      requiresPerItem:
        (p.vault ?? "") === "leave-in-inbox" ||
        (p.vault ?? "unclassified") === "unclassified" ||
        (p.bucket ?? "none") === "none" ||
        (p.bucket === "10_Projects" && p.folder_mode === "create"),
      jobs: list,
    });
  }
  return batches.sort((a, b) => b.count - a.count);
}

export async function listNonTriageReviews(): Promise<Job[]> {
  return (await listJobs({ status: "needs_review" }))
    .filter((job) => job.kind !== "triage.classify")
    .reverse();
}

export async function listRecentFailures(limit = 20): Promise<Job[]> {
  const failed = await listJobs({ status: "failed" });
  return failed.slice(-limit).reverse();
}
