import { promises as fs } from "fs";
import path from "path";
import { spawn } from "child_process";

/**
 * Subscription rate-limit reader for the header usage board.
 *
 * The numbers come from `.claude/scripts/usage_limits.py`, which is the only
 * thing allowed near the OAuth token - this service never touches credentials,
 * it reads the sanitized snapshot the script caches at
 * `.claude/data/state/usage-limits.json` and re-runs the script when that
 * snapshot goes stale.
 *
 * Framework-free (filesystem + child process, no Prisma, no next/*).
 */

const REPO = process.cwd();
const SNAPSHOT = path.join(REPO, ".claude", "data", "state", "usage-limits.json");
const SCRIPT = path.join(".claude", "scripts", "usage_limits.py");
const PYTHON =
  process.env.SECONDBRAIN_PYTHON || "python";

/** How long a cached snapshot is served before we re-run the script. */
const STALE_MS = 120_000;
/** Hard ceiling on the refresh subprocess so a hung network call can't wedge the header. */
const REFRESH_TIMEOUT_MS = 20_000;

export interface LimitWindow {
  id: string;
  label: string;
  used_percent: number;
  remaining_percent: number;
  /** ISO timestamp, or null when the provider did not report one. */
  resets_at: string | null;
}

export interface LimitProvider {
  key: string;
  label: string;
  ok: boolean;
  error: string | null;
  /** "live" = fetched just now; "snapshot" = last value the CLI happened to record. */
  freshness: "live" | "snapshot";
  observed_at: string | null;
  plan?: string | null;
  windows: LimitWindow[];
}

export interface UsageLimits {
  generated_at: string;
  providers: LimitProvider[];
  /** True when these numbers came off disk without a refresh. */
  cached: boolean;
  /** Set when the refresh itself failed; the snapshot may still be usable. */
  refreshError?: string;
}

function isLimitSnapshot(value: unknown): value is Omit<UsageLimits, "cached"> {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.generated_at === "string" && Array.isArray(v.providers);
}

async function readSnapshot(): Promise<Omit<UsageLimits, "cached"> | null> {
  try {
    const raw = await fs.readFile(SNAPSHOT, "utf-8");
    const parsed: unknown = JSON.parse(raw);
    return isLimitSnapshot(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function ageMs(snapshot: { generated_at: string }): number {
  const at = Date.parse(snapshot.generated_at);
  return Number.isNaN(at) ? Number.POSITIVE_INFINITY : Date.now() - at;
}

/**
 * One in-flight refresh at a time. The header polls and several tabs may be
 * open; without this each poll would spawn its own Python process.
 */
let inFlight: Promise<string | null> | null = null;

function runRefresh(): Promise<string | null> {
  if (inFlight) return inFlight;
  inFlight = new Promise<string | null>((resolve) => {
    const child = spawn(PYTHON, [SCRIPT], { cwd: REPO });
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve("refresh timed out");
    }, REFRESH_TIMEOUT_MS);

    child.stderr.on("data", (d) => (stderr += d));
    child.on("close", () => {
      clearTimeout(timer);
      // A non-zero exit means every provider failed; the snapshot it wrote
      // carries the per-provider reasons, so surface those instead of the code.
      resolve(null);
    });
    child.on("error", (e) => {
      clearTimeout(timer);
      resolve(`could not run usage_limits.py: ${stderr.trim() || String(e)}`);
    });
  }).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

/**
 * Current limits for every provider.
 *
 * @param force  Re-run the reader even when the cached snapshot is fresh.
 */
export async function getUsageLimits(force = false): Promise<UsageLimits> {
  const cachedSnapshot = await readSnapshot();
  const needsRefresh = force || !cachedSnapshot || ageMs(cachedSnapshot) > STALE_MS;

  if (!needsRefresh && cachedSnapshot) {
    return { ...cachedSnapshot, cached: true };
  }

  const refreshError = await runRefresh();
  const fresh = await readSnapshot();

  if (fresh) {
    return {
      ...fresh,
      cached: false,
      ...(refreshError ? { refreshError } : {}),
    };
  }
  if (cachedSnapshot) {
    return {
      ...cachedSnapshot,
      cached: true,
      refreshError: refreshError ?? "no snapshot could be written",
    };
  }
  return {
    generated_at: new Date().toISOString(),
    providers: [],
    cached: false,
    refreshError: refreshError ?? "no usage snapshot available yet",
  };
}

/** The window closest to exhaustion, used for the collapsed header badge. */
export function tightestWindow(
  limits: UsageLimits,
): { provider: LimitProvider; window: LimitWindow } | null {
  let best: { provider: LimitProvider; window: LimitWindow } | null = null;
  for (const provider of limits.providers) {
    if (!provider.ok) continue;
    for (const window of provider.windows) {
      if (!best || window.remaining_percent < best.window.remaining_percent) {
        best = { provider, window };
      }
    }
  }
  return best;
}
