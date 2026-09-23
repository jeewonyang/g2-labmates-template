/**
 * Has a scheduled team actually produced work on its cadence?
 *
 * A failed job already shows as a red tally, but a run that never happened
 * leaves nothing behind: the weekly security audit silently skipped
 * 2026-08-31 and 2026-09-14, and its 2026-09-07 jobs all failed within seconds,
 * so for four weeks the pod looked the same as a healthy one. This measures the
 * gap since the last job that did its work.
 *
 * Only weekly teams are judged. Their producer enqueues every kind on every
 * run, so silence means the run did not happen. A daily producer legitimately
 * enqueues nothing when there is nothing to do (no new papers, no captures),
 * and treating that as overdue would be a false alarm.
 *
 * Pure: no filesystem, no clock. The caller passes `now`.
 */

/**
 * Statuses that mean the job ran and produced its output. A rejected job
 * counts: the question is whether the run happened, not whether they agreed.
 */
const SUCCEEDED = new Set([
  "needs_review",
  "approved",
  "rejected",
  "completed",
  "superseded",
]);

/** A weekly run is overdue once a full week plus a day of slack has passed. */
export const WEEKLY_GRACE_MS = 8 * 24 * 60 * 60 * 1000;

export interface CadenceJob {
  status: string;
  created_ts?: string;
}

export interface CadenceStatus {
  /** When the most recent successful job was created; null if never. */
  lastSuccessIso: string | null;
  overdue: boolean;
}

export function cadenceStatus(
  cadence: string,
  jobs: CadenceJob[],
  now: Date,
): CadenceStatus | null {
  if (cadence !== "weekly") return null;
  // No history at all is a machine that has never run this team (a fresh
  // install, a second laptop), not a missed run.
  if (jobs.length === 0) return { lastSuccessIso: null, overdue: false };
  let last: number | null = null;
  let lastIso: string | null = null;
  for (const job of jobs) {
    if (!SUCCEEDED.has(job.status) || !job.created_ts) continue;
    const at = Date.parse(job.created_ts);
    if (!Number.isFinite(at)) continue;
    if (last === null || at > last) {
      last = at;
      lastIso = job.created_ts;
    }
  }
  return {
    lastSuccessIso: lastIso,
    overdue: last === null || now.getTime() - last > WEEKLY_GRACE_MS,
  };
}
