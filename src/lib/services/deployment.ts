import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

/**
 * What code this dashboard is actually running, and when the machine last
 * checked for newer code.
 *
 * Why it exists (2026-09-16): the owner edits G2 from a laptop, a work
 * computer over Tailscale, and cloud Claude sessions, but one machine serves
 * this page. When a change they watched land does not appear here, the question
 * is "is this machine on it yet?" and nothing on any surface could answer it.
 *
 * It **reports, never asserts** - the same rule the app registry follows. It
 * reads the commit this checkout is on and the tail of the updater's log. It
 * does NOT fetch (a page render must not depend on the network) and it does not
 * claim the auto-update task is registered, because from here that cannot be
 * verified. A missing log says so instead of implying the updater is fine.
 */

const REPO = process.cwd();
const UPDATE_LOG = path.join(REPO, ".claude", "data", "logs", "update.log");

export interface DeploymentStatus {
  /** Short hash of the commit this server is running, or null if git is unreadable. */
  commit: string | null;
  branch: string | null;
  subject: string | null;
  committedAt: string | null;
  /** Tracked files modified on this machine — why an update would be skipped. */
  dirtyFiles: number | null;
  /** Last line of the updater's log, with its timestamp split off. */
  lastCheck: { at: string; message: string } | null;
  /** True when the updater has never run here (no log file). */
  updaterHasNeverRun: boolean;
  error: string | null;
}

async function git(args: string[]): Promise<string | null> {
  try {
    const { stdout } = await run("git", ["-C", REPO, ...args], { timeout: 4000 });
    return stdout.trim();
  } catch {
    return null;
  }
}

/** `2026-09-16 14:05:11 updated abc1234 -> def5678 from origin/main` */
function parseLogLine(line: string): { at: string; message: string } | null {
  const m = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(.*)$/.exec(line.trim());
  return m ? { at: m[1], message: m[2] } : null;
}

export async function getDeploymentStatus(): Promise<DeploymentStatus> {
  const [commit, branch, subject, committedAt, status] = await Promise.all([
    git(["rev-parse", "--short", "HEAD"]),
    git(["rev-parse", "--abbrev-ref", "HEAD"]),
    git(["log", "-1", "--pretty=%s"]),
    git(["log", "-1", "--pretty=%cI"]),
    git(["status", "--porcelain", "--untracked-files=no"]),
  ]);

  let lastCheck: DeploymentStatus["lastCheck"] = null;
  let updaterHasNeverRun = false;
  try {
    const log = await fs.readFile(UPDATE_LOG, "utf8");
    const lines = log.trimEnd().split(/\r?\n/).filter(Boolean);
    // The last line that parsed; a step's indented output is not a checkpoint.
    for (let i = lines.length - 1; i >= 0; i -= 1) {
      const parsed = parseLogLine(lines[i]);
      if (parsed && !lines[i].startsWith("    ")) {
        lastCheck = parsed;
        break;
      }
    }
  } catch {
    updaterHasNeverRun = true;
  }

  return {
    commit,
    branch: branch === "HEAD" ? null : branch,
    subject,
    committedAt,
    dirtyFiles: status === null ? null : status ? status.split(/\r?\n/).filter(Boolean).length : 0,
    lastCheck,
    updaterHasNeverRun,
    error: commit === null ? "git is not readable from the server process" : null,
  };
}
