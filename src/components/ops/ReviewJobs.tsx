"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronDown, ChevronRight, ShieldAlert, X } from "lucide-react";
import { Button, Card } from "@/components/ui/primitives";
import type { Job } from "@/lib/services/ledger";

type Finding = {
  title?: string;
  severity?: string;
  file?: string;
  line?: number;
  detail?: string;
  proposed_fix?: string;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function findings(value: unknown): Finding[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Finding =>
          Boolean(item && typeof item === "object" && !Array.isArray(item)),
      )
    : [];
}

function kindLabel(kind: string | null): string {
  if (kind === "sec.secret_scan") return "Security scan findings";
  if (kind === "sec.stale_docs") return "Documentation drift audit";
  if (kind === "admin.schedule_proposal") return "Calendar proposal";
  return kind?.replaceAll(".", " ") ?? "Agent review";
}

export function ReviewJobs({ jobs }: { jobs: Job[] }) {
  const router = useRouter();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(action: "approve" | "reject", job: Job) {
    setBusy(job.job);
    setError(null);
    try {
      const response = await fetch("/api/ops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, jobIds: [job.job] }),
      });
      if (!response.ok && response.status !== 207) {
        const body = await response.json().catch(() => ({}));
        setError(body.error ?? `Request failed (${response.status})`);
        return;
      }
      router.refresh();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(null);
    }
  }

  if (jobs.length === 0) return null;

  return (
    <div className="space-y-3">
      {error && (
        <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
          {error}
        </div>
      )}
      {jobs.map((job) => {
        const proposal = record(job.proposal);
        const jobFindings = findings(proposal.findings);
        const isOpen = Boolean(open[job.job]);
        const summary =
          typeof proposal.summary === "string" && proposal.summary.trim()
            ? proposal.summary
            : "This agent result needs a decision before any effect is applied.";

        return (
          <Card key={job.job} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <button
                  onClick={() =>
                    setOpen((current) => ({
                      ...current,
                      [job.job]: !current[job.job],
                    }))
                  }
                  aria-expanded={isOpen}
                  className="flex items-center gap-2 text-left font-medium text-[var(--ink)]"
                >
                  {isOpen ? (
                    <ChevronDown className="h-4 w-4 shrink-0" />
                  ) : (
                    <ChevronRight className="h-4 w-4 shrink-0" />
                  )}
                  <ShieldAlert className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                  <span>{kindLabel(job.kind)}</span>
                </button>
                <p className="mt-1 text-sm text-[var(--ink-3)]">{summary}</p>
                <p className="mt-1 font-mono text-[10px] uppercase text-[var(--ink-3)]">
                  {job.kind} · {jobFindings.length || 1} review item
                  {(jobFindings.length || 1) === 1 ? "" : "s"}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  onClick={() => act("approve", job)}
                  disabled={busy === job.job}
                >
                  <Check className="h-3.5 w-3.5" />
                  {busy === job.job ? "Working…" : "Approve"}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => act("reject", job)}
                  disabled={busy === job.job}
                >
                  <X className="h-3.5 w-3.5" />
                  Reject
                </Button>
              </div>
            </div>

            {isOpen && (
              <div className="mt-3 space-y-3 border-t border-[var(--rule)] pt-3">
                {jobFindings.length > 0 ? (
                  jobFindings.map((finding, index) => (
                    <div
                      key={`${finding.title ?? "finding"}-${index}`}
                      className="rounded-[var(--radius-sm)] bg-[var(--bg)] p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-[var(--ink)]">
                          {finding.title ?? `Finding ${index + 1}`}
                        </span>
                        {finding.severity && (
                          <span className="rounded-full bg-amber-100 px-2 py-0.5 font-mono text-[10px] uppercase text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                            {finding.severity}
                          </span>
                        )}
                      </div>
                      {finding.file && (
                        <p className="mt-1 break-all font-mono text-xs text-[var(--ink-2)]">
                          {finding.file}
                          {finding.line ? `:${finding.line}` : ""}
                        </p>
                      )}
                      {finding.detail && (
                        <p className="mt-2 text-xs leading-relaxed text-[var(--ink-3)]">
                          {finding.detail}
                        </p>
                      )}
                      {finding.proposed_fix && (
                        <p className="mt-2 text-xs leading-relaxed text-[var(--ink-2)]">
                          <span className="font-medium">Proposed fix:</span>{" "}
                          {finding.proposed_fix}
                        </p>
                      )}
                    </div>
                  ))
                ) : (
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--bg)] p-3 text-xs text-[var(--ink-2)]">
                    {JSON.stringify(job.proposal, null, 2)}
                  </pre>
                )}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
