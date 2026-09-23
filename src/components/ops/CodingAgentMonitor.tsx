"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import {
  CheckCircle2,
  Clock3,
  Code2,
  Loader2,
  OctagonX,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import {
  cancelG2AgentRunAction,
  dismissAllG2AgentRunsAction,
  dismissG2AgentRunAction,
  getRecentG2AgentRunsAction,
} from "@/lib/actions";
import type { G2AgentRun } from "@/lib/services/g2-agent";

function active(run: G2AgentRun): boolean {
  return ["queued", "running", "cancel_requested"].includes(run.status);
}

function phaseLabel(run: G2AgentRun): string {
  if (run.status === "cancel_requested") return "stopping";
  if (run.status === "cancelled") return "cancelled";
  if (run.status === "queued") return "waiting for the repository";
  if (run.status === "completed") return "completed";
  if (run.status === "failed") return "failed";
  if (run.phase === "assessing") return "checking the working tree";
  if (run.phase === "verifying") return "validating changes";
  return "editing and testing";
}

function elapsed(run: G2AgentRun, now: number): string {
  const start = Date.parse(run.startedAt || run.createdAt);
  const end = Date.parse(run.finishedAt || "") || now;
  if (!Number.isFinite(start)) return "unknown";
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function RunIcon({ run }: { run: G2AgentRun }) {
  if (run.status === "completed") {
    return <CheckCircle2 className="h-4 w-4 text-[var(--green)]" />;
  }
  if (run.status === "failed") {
    return <XCircle className="h-4 w-4 text-[var(--red)]" />;
  }
  if (run.status === "cancelled") {
    return <OctagonX className="h-4 w-4 text-[var(--ink-3)]" />;
  }
  return <Loader2 className="h-4 w-4 animate-spin text-[var(--accent)]" />;
}

export function CodingAgentMonitor({
  initialRuns,
}: {
  initialRuns: G2AgentRun[];
}) {
  const [runs, setRuns] = useState(initialRuns);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const hasActive = useMemo(() => runs.some(active), [runs]);
  const finished = useMemo(() => runs.filter((r) => !active(r)).length, [runs]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!hasActive) return;
    let stopped = false;
    const poll = window.setInterval(() => {
      void getRecentG2AgentRunsAction()
        .then((next) => {
          if (!stopped) setRuns(next);
        })
        .catch(() => undefined);
    }, 2_000);
    return () => {
      stopped = true;
      window.clearInterval(poll);
    };
  }, [hasActive]);

  function cancel(run: G2AgentRun) {
    if (
      !window.confirm(
        `Stop this ${run.provider === "codex" ? "Codex" : "Claude"} run? Changes already made will be preserved and shown here.`,
      )
    ) {
      return;
    }
    setError(null);
    startTransition(async () => {
      try {
        const next = await cancelG2AgentRunAction(run.id);
        setRuns((current) =>
          current.map((candidate) => (candidate.id === next.id ? next : candidate)),
        );
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    });
  }

  function dismissAll() {
    if (
      !window.confirm(
        `Clear ${finished} finished run${finished === 1 ? "" : "s"} from the monitor? The run records are kept on disk; anything still running is left alone.`,
      )
    ) {
      return;
    }
    setError(null);
    startTransition(async () => {
      try {
        setRuns((await dismissAllG2AgentRunsAction()).runs);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    });
  }

  function dismiss(run: G2AgentRun) {
    setError(null);
    startTransition(async () => {
      try {
        setRuns(await dismissG2AgentRunAction(run.id));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    });
  }

  if (runs.length === 0) {
    return (
      <p className="text-sm text-[var(--ink-3)]">
        No coding-agent runs yet. “Build / fix G2” captures will appear here as
        soon as Codex or Claude launches.
      </p>
    );
  }

  return (
    <div className="space-y-3" aria-live="polite">
      {error && (
        <p className="text-xs text-[var(--red)]" role="alert">
          {error}
        </p>
      )}
      {/*
        Bulk clear, because these accumulate one row per "Build / fix G2"
        capture and clearing them one at a time is the kind of chore that just
        does not get done. Live runs are skipped, not refused, so one run in
        flight cannot block tidying the twenty behind it.
      */}
      {finished > 1 && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={dismissAll}
            disabled={pending}
            title="Clear every finished run from the monitor. The run records are kept on disk."
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1 text-xs font-medium text-[var(--ink-3)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] disabled:opacity-50"
          >
            {pending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            Clear {finished} finished
          </button>
        </div>
      )}
      {runs.map((run) => (
        <div
          key={run.id}
          className="rounded-[var(--radius-sm)] border bg-[var(--surface)] p-3"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 items-start gap-2">
              <span className="mt-0.5">
                <RunIcon run={run} />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-[var(--ink)]">
                  <span className="capitalize">{run.provider}</span>
                  <span className="font-normal text-[var(--ink-3)]">
                    {" "}
                    · {phaseLabel(run)}
                  </span>
                </p>
                <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-[var(--ink-2)]">
                  {run.prompt}
                </p>
                <p className="mt-1 flex flex-wrap items-center gap-x-3 font-mono text-[10px] text-[var(--ink-3)]">
                  <span className="inline-flex items-center gap-1">
                    <Clock3 className="h-3 w-3" />
                    {elapsed(run, now)}
                  </span>
                  {run.model && <span>{run.model}</span>}
                  {run.agentPid && <span>agent PID {run.agentPid}</span>}
                  {!run.agentPid && run.runnerPid && (
                    <span>runner PID {run.runnerPid}</span>
                  )}
                  {run.heartbeatAt && active(run) && (
                    <span>
                      heartbeat{" "}
                      {Math.max(
                        0,
                        Math.floor((now - Date.parse(run.heartbeatAt)) / 1000),
                      )}
                      s ago
                    </span>
                  )}
                </p>
              </div>
            </div>
            {/*
              A finished run stayed on this list forever with no way to clear
              it, so one failure from days ago kept the panel — and the agent's
              status everywhere else — looking broken. Dismissing stamps the run
              file rather than deleting it.
            */}
            {!active(run) && (
              <button
                type="button"
                onClick={() => dismiss(run)}
                disabled={pending}
                title="Clear this finished run from the monitor. The run record is kept on disk."
                className="inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1 text-xs font-medium text-[var(--ink-3)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] disabled:opacity-50"
              >
                <X className="h-3.5 w-3.5" />
                Clear
              </button>
            )}
            {active(run) && (
              <button
                type="button"
                onClick={() => cancel(run)}
                disabled={pending || run.status === "cancel_requested"}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] border border-red-300 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:text-red-300 dark:hover:bg-red-950"
              >
                {run.status === "cancel_requested" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <OctagonX className="h-3.5 w-3.5" />
                )}
                {run.status === "cancel_requested" ? "Stopping…" : "Stop"}
              </button>
            )}
          </div>

          {run.changedFiles && run.changedFiles.length > 0 && (
            <div className="mt-3 rounded bg-[var(--surface-2)] px-2.5 py-2 text-xs text-[var(--ink-2)]">
              <span className="font-semibold">Changed files:</span>{" "}
              {run.changedFiles.join(", ")}
            </div>
          )}
          {(run.error || run.result) && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-[var(--accent-ink)]">
                {run.error ? "Run details" : "Agent summary"}
              </summary>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--surface-2)] p-3 text-[11px] leading-relaxed text-[var(--ink-2)]">
                {run.error || run.result}
              </pre>
            </details>
          )}
          {run.checks && run.checks.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-[var(--ink-3)]">
              {run.checks.map((check) => (
                <span key={check.name}>
                  {check.ok ? "✓" : "×"} {check.name}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
      <p className="flex items-center gap-1.5 text-xs text-[var(--ink-3)]">
        <Code2 className="h-3.5 w-3.5" />
        Active runs refresh every two seconds. Stopping never rolls back or
        deletes changes already made.
      </p>
    </div>
  );
}
