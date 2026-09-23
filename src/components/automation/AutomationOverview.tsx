"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Loader2,
  Play,
  ShieldCheck,
} from "lucide-react";
import { runVaultAutomationAction } from "@/lib/actions";
import { Button } from "@/components/ui/primitives";
import { HeartbeatButton } from "@/components/home/HeartbeatButton";

export interface AutomationOverviewData {
  active: number;
  needsAttention: number;
  /** Captures filed in the last `windowDays`, not since the beginning of time. */
  appliedRecently: number;
  windowDays: number;
  failed: number;
  reviewQueue: number;
  heartbeatLastRun: string | null;
  recent: {
    id: string;
    state: string;
    confidence: number | null;
    title: string;
  }[];
}

const STATE_LABEL: Record<string, string> = {
  queued: "Queued",
  local_triage: "Local triage",
  verifying: "Independent verification",
  ready: "Ready to apply",
  applied: "Organized",
  needs_review: "Needs your input",
  failed: "Failed",
  overridden: "Handled manually",
};

/**
 * Capture-automation status and its two run controls, on /ops — the page whose
 * whole job is the queue. The `compact` variant that /today's "Needs you" card
 * used was removed with that card on 2026-08-27 (the owner never used it); the
 * sidebar's Agent Center badge carries the waiting count on every page.
 */
export function AutomationOverview({ data }: { data: AutomationOverviewData }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [started, setStarted] = useState(false);

  const run = () =>
    start(async () => {
      await runVaultAutomationAction();
      setStarted(true);
      window.setTimeout(() => router.refresh(), 1600);
    });

  const healthy = data.failed === 0 && data.needsAttention === 0;

  return (
    <div className="space-y-3">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            className={`mt-0.5 rounded-full p-1.5 ${
              healthy ? "bg-[var(--green-soft)]" : "bg-[var(--amber-soft)]"
            }`}
          >
            {healthy ? (
              <ShieldCheck className="h-4 w-4 text-[var(--green)]" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-[var(--amber)]" />
            )}
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[var(--ink)]">
              {healthy ? "Automation is clear" : `${data.needsAttention} item(s) need you`}
            </p>
            <p className="text-xs leading-5 text-[var(--ink-3)]">
              Local triage → Claude verification → policy-controlled filing and task creation
            </p>
          </div>
        </div>
        {/*
          "Process captures", not "Run cycle". This runs the vault team over
          material already captured — local triage, verification, filing. The
          button beside it ("Check messages & calendar") runs Admin, which
          goes out and looks for new material. Two different systems that read
          as the same action when both are called "run".
        */}
        <Button onClick={run} disabled={pending} size="sm" title="Triage and file captures you have already made. Runs locally and on your subscription — no API credit.">
          {pending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          {pending ? "Starting…" : started ? "Processing…" : "Process captures"}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric label="In progress" value={data.active} icon={Bot} />
        <Metric
          label={`Filed (${data.windowDays}d)`}
          value={data.appliedRecently}
          icon={CheckCircle2}
        />
        <Metric label="Agent review" value={data.reviewQueue} icon={ShieldCheck} />
        <Metric
          label="Failed"
          value={data.failed}
          icon={AlertTriangle}
          alert={data.failed > 0}
        />
      </div>

      {data.recent.length > 0 && (
        <ul className="divide-y divide-[var(--rule)]">
          {data.recent.slice(0, 4).map((item) => (
            <li key={item.id} className="flex min-w-0 items-center gap-2 py-2 text-xs">
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  item.state === "failed" || item.state === "needs_review"
                    ? "bg-[var(--amber)]"
                    : item.state === "applied"
                      ? "bg-[var(--green)]"
                      : "bg-[var(--accent)]"
                }`}
              />
              <span className="min-w-0 flex-1 truncate text-[var(--ink-2)]">
                {item.title}
              </span>
              <span className="shrink-0 text-[var(--ink-3)]">
                {STATE_LABEL[item.state] ?? item.state}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3 text-xs">
        <Link href="/inbox" className="text-[var(--accent-ink)] hover:underline">
          Capture exceptions
        </Link>
        <Link href="/ops" className="text-[var(--accent-ink)] hover:underline">
          Agent review queue
        </Link>
        {data.heartbeatLastRun && (
          <span className="text-[var(--ink-3)]">
            Last integration scan {new Date(data.heartbeatLastRun).toLocaleString()}
          </span>
        )}
        <HeartbeatButton className="ml-auto w-auto" />
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  icon: Icon,
  alert = false,
}: {
  label: string;
  value: number;
  icon: React.ElementType;
  alert?: boolean;
}) {
  return (
    <div className="min-w-0 rounded-[var(--radius-sm)] border bg-[var(--bg)] px-2.5 py-2">
      <div className="flex items-center gap-1.5 text-[11px] text-[var(--ink-3)]">
        <Icon className="h-3 w-3 shrink-0" />
        <span className="truncate">{label}</span>
      </div>
      <p
        className={`mt-1 text-lg font-semibold tabular-nums ${
          alert ? "text-[var(--red)]" : "text-[var(--ink)]"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
