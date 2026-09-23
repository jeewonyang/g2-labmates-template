import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";

export const G2_AGENT_PROVIDERS = ["codex", "claude"] as const;
export type G2AgentProvider = (typeof G2_AGENT_PROVIDERS)[number];
export type G2AgentRunStatus =
  | "queued"
  | "running"
  | "cancel_requested"
  | "cancelled"
  | "completed"
  | "failed";

export type G2AgentRun = {
  id: string;
  provider: G2AgentProvider;
  prompt: string;
  status: G2AgentRunStatus;
  createdAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  result?: string;
  error?: string;
  model?: string;
  phase?: "waiting" | "assessing" | "working" | "verifying" | "finished";
  baseSha?: string;
  changedFiles?: string[];
  checks?: Array<{ name: string; ok: boolean; detail: string }>;
  runnerPid?: number | null;
  agentPid?: number | null;
  heartbeatAt?: string | null;
  cancelRequestedAt?: string | null;
  cancelledBy?: string | null;
  /**
   * Set when they clear a finished run off the monitor. The run file is kept —
   * dismissing is an acknowledgement, not a delete, so the transcript, checks,
   * and changed-file inventory stay on disk for later reference.
   */
  dismissedAt?: string | null;
};

const REPO = process.cwd();
const RUNS_DIR = path.join(
  REPO,
  ".claude",
  "data",
  "state",
  "g2-agent-runs",
);
const PYTHON =
  process.env.SECONDBRAIN_PYTHON ||
  "python";
const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function runPath(id: string): string {
  if (!RUN_ID.test(id)) throw new Error("Invalid G2 agent run id.");
  return path.join(RUNS_DIR, `${id}.json`);
}

async function writeJsonAtomic(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${randomUUID()}.tmp`;
  await fs.writeFile(temp, JSON.stringify(value, null, 2), {
    encoding: "utf8",
    flag: "wx",
  });
  await fs.rename(temp, file);
}

export async function startG2AgentRun(input: {
  prompt: string;
  provider: G2AgentProvider;
  clientRequestId: string;
}): Promise<G2AgentRun> {
  const existing = await getG2AgentRun(input.clientRequestId);
  if (existing) {
    if (existing.prompt !== input.prompt || existing.provider !== input.provider) {
      throw new Error("That request id is already in use.");
    }
    return existing;
  }

  const active = (await listRecentG2AgentRuns(20)).find((candidate) =>
    ["queued", "running", "cancel_requested"].includes(candidate.status),
  );
  if (active) {
    throw new Error(
      `${active.provider === "codex" ? "Codex" : "Claude"} is already working on G2.`,
    );
  }

  const run: G2AgentRun = {
    id: input.clientRequestId,
    provider: input.provider,
    prompt: input.prompt,
    status: "queued",
    phase: "waiting",
    createdAt: new Date().toISOString(),
  };
  const file = runPath(run.id);
  await fs.mkdir(path.dirname(file), { recursive: true });
  try {
    await fs.writeFile(file, JSON.stringify(run, null, 2), {
      encoding: "utf8",
      flag: "wx",
    });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      const raced = await getG2AgentRun(run.id);
      if (raced && raced.prompt === run.prompt && raced.provider === run.provider) {
        return raced;
      }
    }
    throw error;
  }

  const child = spawn(
    PYTHON,
    [".claude/scripts/g2_agent_run.py", "--run-id", run.id],
    {
      cwd: REPO,
      detached: true,
      stdio: "ignore",
      windowsHide: true,
      env: { ...process.env, CLAUDE_INVOKED_BY: "g2-quick-capture" },
    },
  );
  child.on("error", (error) => {
    void writeJsonAtomic(file, {
      ...run,
      status: "failed",
      finishedAt: new Date().toISOString(),
      error: `Could not start the ${run.provider} runner: ${error.message}`,
    });
  });
  child.unref();
  return run;
}

export async function cancelG2AgentRun(id: string): Promise<G2AgentRun> {
  const current = await getG2AgentRun(id);
  if (!current) throw new Error("Coding-agent run not found.");
  if (["completed", "failed", "cancelled"].includes(current.status)) {
    return current;
  }
  await new Promise<void>((resolve, reject) => {
    const child = spawn(
      PYTHON,
      [".claude/scripts/g2_agent_run.py", "--run-id", id, "--cancel"],
      { cwd: REPO, windowsHide: true },
    );
    let error = "";
    child.stderr.on("data", (chunk) => {
      error += String(chunk);
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(error.trim() || "Could not cancel the coding agent."));
    });
  });
  const updated = await getG2AgentRun(id);
  if (!updated) throw new Error("Coding-agent run disappeared during cancellation.");
  return updated;
}

/**
 * Clear a finished run off the monitor.
 *
 * The run file stays on disk with a `dismissedAt` stamp — this is the same
 * soft-archive rule the rest of the app follows, and the checks, changed-file
 * inventory, and error text of a failed run are exactly what they would want
 * back if the failure recurs. An unfinished run cannot be dismissed: hiding a
 * live run would strand the working tree with no visible owner. Stop it first.
 */
export async function dismissG2AgentRun(id: string): Promise<G2AgentRun> {
  const current = await getG2AgentRun(id);
  if (!current) throw new Error("Coding-agent run not found.");
  if (!["completed", "failed", "cancelled"].includes(current.status)) {
    throw new Error("Stop this run before clearing it.");
  }
  if (current.dismissedAt) return current;
  const next: G2AgentRun = { ...current, dismissedAt: new Date().toISOString() };
  await writeJsonAtomic(runPath(id), next);
  return next;
}

/**
 * Clear every finished run at once, and report how many were cleared.
 *
 * Live runs are skipped rather than refused, so one in-flight run does not
 * block clearing a backlog of twenty old ones. Each file is stamped
 * individually — a failure on one leaves the rest cleared, which is the right
 * outcome for a housekeeping action.
 */
export async function dismissFinishedG2AgentRuns(): Promise<number> {
  const runs = await listRecentG2AgentRuns(20);
  let cleared = 0;
  for (const run of runs) {
    if (["queued", "running", "cancel_requested"].includes(run.status)) continue;
    try {
      await dismissG2AgentRun(run.id);
      cleared += 1;
    } catch {
      // Skip the one that raced; the rest still clear.
    }
  }
  return cleared;
}

export async function getG2AgentRun(id: string): Promise<G2AgentRun | null> {
  try {
    const file = runPath(id);
    const run = JSON.parse(await fs.readFile(file, "utf8")) as G2AgentRun;
    const reference = Date.parse(
      run.heartbeatAt || run.startedAt || run.createdAt,
    );
    const staleAfter =
      run.status === "queued" ? 10 * 60_000 : 40 * 60_000;
    if (
      ["queued", "running", "cancel_requested"].includes(run.status) &&
      Number.isFinite(reference) &&
      Date.now() - reference > staleAfter
    ) {
      const stale: G2AgentRun = {
        ...run,
        status: run.status === "cancel_requested" ? "cancelled" : "failed",
        phase: "finished",
        finishedAt: new Date().toISOString(),
        error:
          run.status === "cancel_requested"
            ? "Cancellation was requested and the detached run stopped reporting."
            : "This detached run stopped reporting and was marked interrupted.",
      };
      await writeJsonAtomic(file, stale);
      return stale;
    }
    return run;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

/**
 * How many runs have ever finished in each state, dismissed ones included.
 *
 * The monitor lists at most 20 undismissed runs, and they clear every finished
 * run off it, so a "done" tally folded from that list read 0 no matter how many
 * fixes Cody had landed. Dismissing is an acknowledgement, not an erasure: the
 * run files stay on disk, and this counts them all - the same lifetime count
 * the ledger teams show under "done".
 */
export async function countG2AgentRuns(): Promise<Record<G2AgentRunStatus, number>> {
  const totals: Record<G2AgentRunStatus, number> = {
    queued: 0,
    running: 0,
    cancel_requested: 0,
    cancelled: 0,
    completed: 0,
    failed: 0,
  };
  let names: string[];
  try {
    names = await fs.readdir(RUNS_DIR);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return totals;
    throw error;
  }
  for (const name of names) {
    if (!name.endsWith(".json") || !RUN_ID.test(name.slice(0, -5))) continue;
    try {
      const run = JSON.parse(await fs.readFile(path.join(RUNS_DIR, name), "utf8")) as G2AgentRun;
      if (run.status in totals) totals[run.status] += 1;
    } catch {
      // A half-written or unreadable file is skipped, as in the listing.
    }
  }
  return totals;
}

export async function listRecentG2AgentRuns(
  limit = 5,
  opts: { includeDismissed?: boolean } = {},
): Promise<G2AgentRun[]> {
  const safeLimit = Math.max(1, Math.min(limit, 20));
  let names: string[];
  try {
    names = await fs.readdir(RUNS_DIR);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
  const runs = await Promise.all(
    names
      .filter((name) => name.endsWith(".json") && RUN_ID.test(name.slice(0, -5)))
      .map(async (name) => {
        try {
          return await getG2AgentRun(name.slice(0, -5));
        } catch {
          return null;
        }
      }),
  );
  return runs
    .filter((run): run is G2AgentRun => Boolean(run?.createdAt))
    .filter((run) => opts.includeDismissed || !run.dismissedAt)
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
    .slice(0, safeLimit);
}
