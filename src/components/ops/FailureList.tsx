"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2, Trash2, X } from "lucide-react";
import type { Job } from "@/lib/services/ledger";

/**
 * Recent ledger failures, with a way to acknowledge them.
 *
 * This panel was read-only, so a failure sat here forever and the only way to
 * clear one was the `ledger.py resolve` CLI — unrunnable from the tablet
 * /ops is often read on. Dismissing posts that same transition (`failed -> resolved`),
 * which is append-only: the failure, its error text, and its payload stay in
 * the ledger history. What changes is that it stops occupying the panel and
 * stops counting toward the "Failed" stat.
 *
 * Deliberately not a retry. Re-running a failed job is `retry_failures.py`'s
 * business and a different decision; conflating "I have seen this" with "do it
 * again" in one button is how you get surprise re-runs.
 */
function relative(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const mins = Math.floor((Date.now() - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function FailureList({ failures }: { failures: Job[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function resolve(jobIds: string[], key: string) {
    setBusy(key);
    setError(null);
    try {
      const res = await fetch("/api/ops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "resolve", jobIds }),
      });
      const body = (await res.json().catch(() => ({}))) as {
        error?: string;
        failed?: unknown[];
      };
      if (!res.ok || body.failed?.length) {
        throw new Error(body.error ?? `Request failed (${res.status}).`);
      }
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-2">
      {error && (
        <p className="text-xs text-[var(--red)]" role="alert">
          {error}
        </p>
      )}

      {failures.length > 1 && (
        <div className="flex justify-end">
          <button
            type="button"
            disabled={busy !== null}
            title="Mark every failure here as seen. The ledger history is kept."
            onClick={() => {
              if (
                !window.confirm(
                  `Dismiss all ${failures.length} failures? They stay in the ledger history — this only clears the panel and the Failed count.`,
                )
              ) {
                return;
              }
              void resolve(
                failures.map((f) => f.job),
                "all",
              );
            }}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1 text-xs font-medium text-[var(--ink-3)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] disabled:opacity-50"
          >
            {busy === "all" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            Dismiss all {failures.length}
          </button>
        </div>
      )}

      <ul className="space-y-2">
        {failures.map((f) => (
          <li key={f.job} className="text-sm">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
              <div className="min-w-0 flex-1">
                <p className="font-mono text-xs text-[var(--ink-2)]">
                  {f.kind} · {relative(f.updated_ts ?? null)}
                  {f.retryable === false && (
                    <span className="ml-2 rounded bg-red-100 px-1 text-[10px] uppercase text-red-800 dark:bg-red-950 dark:text-red-300">
                      not retryable
                    </span>
                  )}
                </p>
                <p className="text-xs text-[var(--ink-3)]">{f.error}</p>
              </div>
              <button
                type="button"
                aria-label="Dismiss this failure"
                title="Mark as seen. The failure stays in the ledger history."
                disabled={busy !== null}
                onClick={() => void resolve([f.job], f.job)}
                className="shrink-0 rounded p-1 text-[var(--ink-3)] opacity-70 transition-opacity hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] hover:opacity-100 disabled:opacity-40"
              >
                {busy === f.job ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <X className="h-3.5 w-3.5" />
                )}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
