"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Bot,
  ChevronDown,
  ChevronRight,
  Clock,
  FileJson,
  Loader2,
  XCircle,
} from "lucide-react";
import type { Job } from "@/lib/services/ledger";

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function summary(job: Job): string {
  const payload = record(job.payload);
  const sender = String(payload.sender ?? "").trim();
  const nextAction = String(payload.next_action ?? "").trim();
  const sourcePath = String(payload.path ?? "").trim();
  if (nextAction) return nextAction;
  if (job.kind === "draft.reply" && sender) return `Draft a reply to ${sender}`;
  if (job.kind === "admin.extract_commitments" && sender) {
    return `Extract next actions from ${sender}`;
  }
  if (sourcePath) {
    const name = sourcePath.replaceAll("\\", "/").split("/").pop();
    return `${job.kind ?? "Agent job"} · ${name}`;
  }
  return job.kind?.replaceAll(".", " → ") || "Agent job";
}

function relative(iso: string | undefined, renderedAt: number): string {
  const timestamp = Date.parse(iso ?? "");
  if (!Number.isFinite(timestamp)) return "unknown";
  const minutes = Math.max(0, Math.floor((renderedAt - timestamp) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function details(job: Job): string {
  return JSON.stringify(
    {
      payload: job.payload,
      proposal: job.proposal,
      result: job.result,
      error: job.error,
    },
    null,
    2,
  ).slice(0, 20_000);
}

/** A deferred job is queued but the dispatcher will not hand it out before this time. */
function waitingUntil(job: Job): Date | null {
  if (job.status !== "created" || !job.not_before) return null;
  const at = new Date(job.not_before);
  if (Number.isNaN(at.getTime()) || at.getTime() <= Date.now()) return null;
  return at;
}

function statusLabel(job: Job): string {
  if (job.status === "created") return waitingUntil(job) ? "waiting for reset" : "queued";
  if (job.status === "claimed") return "running";
  return job.status.replaceAll("_", " ");
}

export function JobQueue({
  jobs,
  initialJob,
  renderedAt,
  queuedSlackDraftJobIds,
}: {
  jobs: Job[];
  initialJob?: string;
  renderedAt: number;
  queuedSlackDraftJobIds: string[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState<string | null>(initialJob ?? null);
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);

  async function cancelTargets({
    ids,
    hasRunning,
    allDrafts,
  }: {
    ids: string[];
    hasRunning: boolean;
    allDrafts: boolean;
  }) {
    if (!ids.length) return;
    const prompt = hasRunning
      ? `Cancel ${ids.length} job${ids.length === 1 ? "" : "s"}? Running model work will be stopped and any result will be ignored.`
      : `Cancel ${ids.length} queued job${ids.length === 1 ? "" : "s"}? The audit records will remain.`;
    if (!window.confirm(prompt)) return;

    setCancelling((current) => new Set([...current, ...ids]));
    setMessage(null);
    try {
      const response = await fetch("/api/ops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "cancel",
          jobIds: ids,
          reason:
            allDrafts
              ? "old Slack reply draft no longer needed"
              : "no longer needed",
        }),
      });
      const body = (await response.json().catch(() => ({}))) as {
        applied?: number;
        error?: string;
        failed?: unknown[];
      };
      if (!response.ok && response.status !== 207) {
        throw new Error(body.error ?? `Cancellation failed (${response.status}).`);
      }
      const failed = body.failed?.length ?? 0;
      setMessage(
        failed
          ? `Cancelled ${body.applied ?? 0}; ${failed} had already changed state.`
          : `Cancelled ${body.applied ?? ids.length} job${ids.length === 1 ? "" : "s"}.`,
      );
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setCancelling((current) => {
        const next = new Set(current);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  function cancelJobs(targets: Job[]) {
    return cancelTargets({
      ids: targets.map((job) => job.job),
      hasRunning: targets.some((job) => job.status === "claimed"),
      allDrafts: targets.every((job) => job.kind === "draft.reply"),
    });
  }

  return (
    <div>
      {(queuedSlackDraftJobIds.length > 0 || message) && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {queuedSlackDraftJobIds.length > 0 && (
            <button
              type="button"
              onClick={() =>
                void cancelTargets({
                  ids: queuedSlackDraftJobIds,
                  hasRunning: false,
                  allDrafts: true,
                })
              }
              disabled={queuedSlackDraftJobIds.some((id) => cancelling.has(id))}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-red-300 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:text-red-300 dark:hover:bg-red-950"
            >
              {queuedSlackDraftJobIds.some((id) => cancelling.has(id)) ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <XCircle className="h-3.5 w-3.5" />
              )}
              Cancel {queuedSlackDraftJobIds.length} queued Slack draft
              {queuedSlackDraftJobIds.length === 1 ? "" : "s"}
            </button>
          )}
          {message && (
            <span className="text-xs text-[var(--ink-3)]" role="status">
              {message}
            </span>
          )}
        </div>
      )}
      <ul className="space-y-2">
      {jobs.map((job) => {
        const isOpen = open === job.job;
        const payload = record(job.payload);
        const taskId = String(payload.task_id ?? "");
        return (
          <li
            key={job.job}
            className="overflow-hidden rounded-[var(--radius-sm)] border bg-[var(--surface)]"
          >
            <button
              onClick={() => setOpen(isOpen ? null : job.job)}
              aria-expanded={isOpen}
              className="flex w-full items-start gap-3 p-3 text-left transition-colors hover:bg-[var(--surface-hover)]"
            >
              <span className="mt-0.5 rounded bg-[var(--accent-soft)] p-1.5 text-[var(--accent-ink)]">
                <Bot className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-[var(--ink)]">
                  {summary(job)}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] text-[var(--ink-3)]">
                  <span>{job.kind}</span>
                  <span>·</span>
                  <span>{job.runtime ?? "local"}</span>
                  <span>·</span>
                  <span>{job.sensitivity}</span>
                  <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {relative(job.created_ts, renderedAt)}
                  </span>
                </span>
              </span>
              <span className="rounded-full bg-[var(--surface-2)] px-2 py-0.5 font-mono text-[10px] uppercase text-[var(--ink-2)]">
                {statusLabel(job)}
              </span>
              {isOpen ? (
                <ChevronDown className="mt-1 h-4 w-4 text-[var(--ink-3)]" />
              ) : (
                <ChevronRight className="mt-1 h-4 w-4 text-[var(--ink-3)]" />
              )}
            </button>

            {isOpen && (
              <div className="border-t bg-[var(--bg)] p-3">
                <dl className="grid gap-2 text-xs sm:grid-cols-2">
                  <div>
                    <dt className="font-mono uppercase text-[var(--ink-3)]">
                      Job ID
                    </dt>
                    <dd className="mt-0.5 break-all text-[var(--ink-2)]">
                      {job.job}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-mono uppercase text-[var(--ink-3)]">
                      Source
                    </dt>
                    <dd className="mt-0.5 text-[var(--ink-2)]">
                      {String(
                        payload.sender ??
                          payload.source_id ??
                          payload.path ??
                          "Agent OS",
                      )}
                    </dd>
                  </div>
                </dl>
                {job.status === "created" && (
                  <p className="mt-3 rounded bg-[var(--accent-soft)] px-3 py-2 text-xs text-[var(--accent-ink)]">
                    {waitingUntil(job)
                      ? `A subscription window is spent. This job waits until ${waitingUntil(job)!.toLocaleString(
                          "en-US",
                          { weekday: "short", hour: "numeric", minute: "2-digit" },
                        )} and the next scheduled run after that picks it up${
                          job.defer_reason ? ` (${job.defer_reason.slice(0, 160)})` : ""
                        }.`
                      : "Queued means waiting for an agent. This job is not currently running."}
                  </p>
                )}
                <div className="mt-3">
                  <p className="mb-1 flex items-center gap-1 font-mono text-[10px] uppercase text-[var(--ink-3)]">
                    <FileJson className="h-3 w-3" />
                    Job details
                  </p>
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--surface-2)] p-3 text-[11px] leading-relaxed text-[var(--ink-2)]">
                    {details(job)}
                  </pre>
                </div>
                <div className="mt-3 flex gap-3 text-xs">
                  {(job.status === "created" || job.status === "claimed") && (
                    <button
                      type="button"
                      onClick={() => void cancelJobs([job])}
                      disabled={cancelling.has(job.job)}
                      className="inline-flex items-center gap-1 text-red-700 hover:underline disabled:opacity-50 dark:text-red-300"
                    >
                      {cancelling.has(job.job) ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <XCircle className="h-3 w-3" />
                      )}
                      {job.status === "claimed" ? "Stop running job" : "Cancel job"}
                    </button>
                  )}
                  {job.kind === "draft.reply" && (
                    <Link href="/drafts" className="text-[var(--accent-ink)] hover:underline">
                      Open drafts
                    </Link>
                  )}
                  {taskId && (
                    <Link href="/today" className="text-[var(--accent-ink)] hover:underline">
                      Open linked task
                    </Link>
                  )}
                </div>
              </div>
            )}
          </li>
        );
      })}
      </ul>
    </div>
  );
}
