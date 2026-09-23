import { promises as fs } from "node:fs";
import path from "node:path";
import { db } from "@/lib/db";
import { listJobs, type Job } from "@/lib/services/ledger";

const REPO = process.cwd();
const DRAFTS = path.join(REPO, "VAULT", "Memory", "drafts", "active");
const ACTIVITY_STATE = path.join(
  REPO,
  ".claude",
  "data",
  "state",
  "activity-seen.json",
);

export type AgentActivityTone = "info" | "success" | "attention" | "error";

export interface AgentActivityItem {
  id: string;
  at: string;
  title: string;
  detail: string;
  href: string;
  tone: AgentActivityTone;
  category: "task" | "draft" | "job" | "automation";
}

export async function getActivitySeenAt(): Promise<Date | null> {
  try {
    const raw = JSON.parse(await fs.readFile(ACTIVITY_STATE, "utf8")) as {
      seenAt?: string;
    };
    const seen = new Date(raw.seenAt ?? "");
    return Number.isFinite(seen.getTime()) ? seen : null;
  } catch {
    return null;
  }
}

export async function markActivitySeen(at = new Date()): Promise<Date> {
  await fs.mkdir(path.dirname(ACTIVITY_STATE), { recursive: true });
  const temp = `${ACTIVITY_STATE}.${process.pid}.tmp`;
  await fs.writeFile(temp, JSON.stringify({ seenAt: at.toISOString() }), "utf8");
  await fs.rename(temp, ACTIVITY_STATE);
  return at;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function short(value: unknown, fallback = ""): string {
  return String(value ?? fallback).replace(/\s+/g, " ").trim().slice(0, 180);
}

function jobSubject(job: Job): string {
  const payload = record(job.payload);
  const sender = short(payload.sender);
  const sourcePath = short(payload.path);
  const nextAction = short(payload.next_action);
  switch (job.kind) {
    case "draft.reply":
      return sender ? `Reply draft for ${sender}` : "Reply draft";
    case "admin.extract_commitments":
      return sender ? `Commitment check for ${sender}` : "Commitment check";
    case "admin.schedule_proposal":
      return sender ? `Schedule check for ${sender}` : "Schedule check";
    case "triage.classify":
      return sourcePath
        ? `Classify ${path.basename(sourcePath)}`
        : "Classify an inbox item";
    case "triage.review":
      return "Verify a filing decision";
    case "wiki.ingest":
      return sourcePath
        ? `Update wiki from ${path.basename(sourcePath)}`
        : "Update the wiki";
    default:
      return nextAction || short(job.kind, "Agent job");
  }
}

/**
 * Job statuses worth interrupting for.
 *
 * `created`, `claimed`, and `completed` are the pipeline talking about itself:
 * a healthy run emits all three for every job, which turned the drawer into a
 * progress log nobody reads. Only the two states that need the owner — a job
 * waiting on their decision, and one that broke — are reported. Progress is
 * still fully visible on /ops and /teams, which is where you go to watch.
 */
const REPORTABLE_JOB_STATUS = new Set(["needs_review", "failed"]);

function activityForJob(job: Job): AgentActivityItem | null {
  const at = job.updated_ts ?? job.created_ts;
  if (!at) return null;
  const status = job.status;
  if (!REPORTABLE_JOB_STATUS.has(status)) return null;
  const subject = jobSubject(job);
  return {
    id: `job:${job.job}:${status}`,
    at,
    title:
      status === "failed" ? `Failed: ${subject}` : `Needs review: ${subject}`,
    detail:
      status === "failed"
        ? short(job.error, "The job failed.")
        : `${short(job.kind, "agent")} · waiting on your decision`,
    href: `/ops?job=${encodeURIComponent(job.job)}`,
    tone: status === "failed" ? "error" : "attention",
    category: "job",
  };
}

async function recentDrafts(since: Date): Promise<AgentActivityItem[]> {
  let names: string[];
  try {
    names = await fs.readdir(DRAFTS);
  } catch {
    return [];
  }
  const out: AgentActivityItem[] = [];
  for (const name of names) {
    if (!name.endsWith(".md")) continue;
    try {
      const stat = await fs.stat(path.join(DRAFTS, name));
      if (stat.mtime < since) continue;
      const raw = await fs.readFile(path.join(DRAFTS, name), "utf8");
      const type = raw.match(/^type:\s*(.+)$/m)?.[1]?.trim() || "email";
      const recipient =
        raw.match(/^recipient:\s*(.+)$/m)?.[1]?.trim() || "unknown recipient";
      out.push({
        id: `draft:${name}:${stat.mtimeMs}`,
        at: stat.mtime.toISOString(),
        title: `${type === "slack" ? "Slack" : "Email"} reply drafted`,
        detail: `Reply for ${recipient}`,
        href: "/drafts",
        tone: "success",
        category: "draft",
      });
    } catch {
      continue;
    }
  }
  return out;
}

export async function listAgentActivity(
  since: Date,
  limit = 80,
): Promise<AgentActivityItem[]> {
  const [jobs, tasks, automationEvents, drafts] = await Promise.all([
    listJobs(),
    db.task.findMany({
      where: {
        createdAt: { gte: since },
        description: { contains: "[agent-source:" },
      },
      select: { id: true, title: true, priority: true, createdAt: true },
      take: 40,
      orderBy: { createdAt: "desc" },
    }),
    db.automationEvent.findMany({
      where: { createdAt: { gte: since } },
      include: {
        automation: {
          include: {
            inboxItem: {
              select: {
                parsedTitle: true,
                rawText: true,
                processedIntoType: true,
                processedIntoId: true,
              },
            },
          },
        },
      },
      take: 40,
      orderBy: { createdAt: "desc" },
    }),
    recentDrafts(since),
  ]);

  const items: AgentActivityItem[] = [...drafts];
  const recentJobs: Job[] = [];
  for (const job of jobs) {
    const at = Date.parse(job.updated_ts ?? job.created_ts ?? "");
    if (!Number.isFinite(at) || at < since.getTime()) continue;
    if (!REPORTABLE_JOB_STATUS.has(job.status)) continue;
    recentJobs.push(job);
  }
  const jobGroups = new Map<string, Job[]>();
  for (const job of recentJobs) {
    const key = `${job.status}:${job.kind ?? "unknown"}`;
    const group = jobGroups.get(key);
    if (group) group.push(job);
    else jobGroups.set(key, [job]);
  }
  for (const group of jobGroups.values()) {
    group.sort((a, b) =>
      (b.updated_ts ?? b.created_ts ?? "").localeCompare(
        a.updated_ts ?? a.created_ts ?? "",
      ),
    );
    const latest = group[0];
    const item = activityForJob(latest);
    if (!item) continue;
    if (group.length > 1) {
      item.id = `job-group:${latest.status}:${latest.kind}:${item.at}`;
      item.title = `${group.length} ${latest.kind} jobs · ${latest.status.replaceAll("_", " ")}`;
      item.detail = `${latest.runtime ?? "local"} · click to inspect the queue`;
      item.href = `/ops?kind=${encodeURIComponent(latest.kind ?? "")}`;
    }
    items.push(item);
  }
  for (const task of tasks) {
    items.push({
      id: `task:${task.id}:${task.createdAt.getTime()}`,
      at: task.createdAt.toISOString(),
      title: "Agent added a task",
      detail: `${task.title} · ${task.priority}`,
      href: "/today",
      tone: "attention",
      category: "task",
    });
  }
  const eventGroups = new Map<string, typeof automationEvents>();
  for (const event of automationEvents) {
    // `overridden` means the owner triaged the capture themselves. Reporting their own
    // action back to them is the definition of noise.
    if (!["applied", "failed"].includes(event.type)) continue;
    const group = eventGroups.get(event.type);
    if (group) group.push(event);
    else eventGroups.set(event.type, [event]);
  }
  for (const [type, group] of eventGroups) {
    const latest = group[0];
    const inbox = latest.automation.inboxItem;
    const label = short(inbox.parsedTitle || inbox.rawText, "Captured item");
    items.push({
      id: `automation-group:${type}:${latest.createdAt.getTime()}`,
      at: latest.createdAt.toISOString(),
      title:
        type === "applied"
          ? `${group.length} capture${group.length === 1 ? "" : "s"} filed automatically`
          : `${group.length} capture automation failure${group.length === 1 ? "" : "s"}`,
      detail:
        type === "applied"
          ? `${group.length === 1 ? label : `Latest: ${label}`} · correct it on the Inbox if it landed wrong`
          : group.length === 1
            ? label
            : `Latest: ${label}`,
      // Filed captures link to the Inbox, where "Recently organized by G2"
      // offers the decline-and-edit that teaches the classifier.
      href: "/inbox",
      tone: type === "failed" ? "error" : "success",
      category: "automation",
    });
  }
  // No vault-update rows (removed 2026-07-31, the owner: "sent too frequently").
  // Every team writes a dated file on every scheduled run, so this fired on a
  // healthy quiet day and needed nothing from them — the same self-narration the
  // job-status filter above removes. Grouping it one row per team slowed the
  // count down but not the frequency: five teams on a daily cadence is still a
  // badge every day for work that is already visible on /teams and /vault, and
  // which the CEO brief on /today summarizes. Anything in a vault file that
  // *does* need their comes through its own row (needs_review, failed, drafts).
  // Do not re-add this without a new signal — "a file was written" is not one.

  return items
    .sort((a, b) => b.at.localeCompare(a.at))
    .filter(
      (item, index, all) =>
        all.findIndex(
          (candidate) =>
            candidate.title === item.title &&
            candidate.detail === item.detail &&
            candidate.at === item.at,
        ) === index,
    )
    .slice(0, Math.max(1, Math.min(limit, 100)));
}
