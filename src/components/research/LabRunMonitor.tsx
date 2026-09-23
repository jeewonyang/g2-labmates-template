"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { Loader2, Square, X } from "lucide-react";
import { cancelLabRunAction, dismissLabRunAction, getLabRunsAction } from "@/lib/actions";
import { Badge } from "@/components/ui/Badge";
import type { LabRun } from "@/lib/services/labNotebook";

const LIVE = new Set(["queued", "running", "cancel_requested"]);

const PHASE: Record<string, string> = {
  waiting: "waiting for the previous run",
  pipeline: "running the pipeline",
  agent: "agent interpreting",
  notebook: "filing the notebook entry",
  finished: "finished",
};

const TONE: Record<string, "gray" | "green" | "amber" | "red" | "blue"> = {
  queued: "gray",
  running: "blue",
  cancel_requested: "amber",
  cancelled: "gray",
  completed: "green",
  failed: "red",
};

/** Recent runs; polls every 5 s while one is live. The pose is derived from status, never chosen. */
export function LabRunMonitor({ initial }: { initial: LabRun[] }) {
  const router = useRouter();
  const [runs, setRuns] = useState(initial);
  const [, start] = useTransition();
  const live = runs.some((r) => LIVE.has(r.status));

  useEffect(() => setRuns(initial), [initial]);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(async () => {
      const next = await getLabRunsAction();
      setRuns(next);
      if (!next.some((r) => LIVE.has(r.status))) router.refresh();
    }, 5_000);
    return () => clearInterval(timer);
  }, [live, router]);

  const act = (fn: () => Promise<unknown>) =>
    start(async () => {
      await fn();
      setRuns(await getLabRunsAction());
      router.refresh();
    });

  if (!runs.length) {
    return <p className="text-sm text-[var(--ink-3)]">No runs yet.</p>;
  }

  return (
    <ul className="divide-y">
      {runs.map((run) => (
        <li key={run.id} className="py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={TONE[run.status] ?? "gray"} dot>
              {run.status.replace("_", " ")}
            </Badge>
            <span className="text-sm font-medium text-[var(--ink)]">
              {run.notebookTitle || `${run.projectCode} · ${run.assay}`}
            </span>
            {run.name && <span className="text-xs text-[var(--ink-2)]">{run.name}</span>}
            <span className="ml-auto flex items-center gap-1">
              {LIVE.has(run.status) ? (
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
                  onClick={() => act(() => cancelLabRunAction(run.id))}
                  title="Stop this run"
                >
                  <Square className="h-3 w-3" /> Stop
                </button>
              ) : (
                <button
                  type="button"
                  className="rounded p-1 text-[var(--ink-3)] hover:bg-[var(--surface-hover)]"
                  onClick={() => act(() => dismissLabRunAction(run.id))}
                  title="Clear from this list (the run record is kept)"
                  aria-label="Clear run"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </span>
          </div>
          <p className="mt-1 flex items-center gap-1 text-xs text-[var(--ink-3)]">
            {LIVE.has(run.status) && <Loader2 className="h-3 w-3 animate-spin" />}
            {run.mode === "pipeline" ? "pipeline only" : run.model || "claude"} ·{" "}
            {PHASE[run.phase || "waiting"] ?? run.phase} · started{" "}
            {new Date(run.startedAt || run.createdAt).toLocaleString()}
          </p>
          <p className="mt-0.5 break-all font-mono text-[11px] text-[var(--ink-3)]">in: {run.inputPath}</p>
          {run.resultPath && (
            <p className="break-all font-mono text-[11px] text-[var(--ink-3)]">out: {run.resultPath}</p>
          )}
          {run.error && <p className="mt-1 text-xs text-[var(--red)]">{run.error}</p>}
          {run.notebook && (
            <Link
              href={`/research/notebook/${run.notebook.projectCode}/${run.notebook.title}`}
              className="mt-1 inline-block text-xs text-[var(--accent-ink)] hover:underline"
            >
              Open notebook entry →
            </Link>
          )}
        </li>
      ))}
    </ul>
  );
}
