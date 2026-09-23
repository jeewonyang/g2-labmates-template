"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Play } from "lucide-react";

/**
 * A one-press trigger for a maintenance action /ops used to describe in prose.
 *
 * Every panel here that says "a worker died" or "work is queued" used to end
 * with a command to go type in a terminal. The command is the same one this
 * button runs, so the instruction was pure friction — and unrunnable from a
 * tablet over the tailnet, which is where this page is often read.
 *
 * Deliberately narrow: it posts one named action to /api/ops and refreshes.
 * It cannot approve, reject, or file anything — those stay explicit per-item
 * decisions elsewhere on the page.
 */
export function OpsActionButton({
  action,
  label,
  busyLabel,
  title,
}: {
  action: "reap" | "drain";
  label: string;
  busyLabel: string;
  title?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function run() {
    setBusy(true);
    setMessage(null);
    setFailed(false);
    try {
      const res = await fetch("/api/ops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const body = (await res.json().catch(() => ({}))) as {
        message?: string;
        error?: string;
      };
      if (!res.ok && res.status !== 202) {
        setFailed(true);
        setMessage(body.error ?? `Request failed (${res.status})`);
      } else {
        setMessage(body.message ?? "Done.");
        router.refresh();
      }
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button
        onClick={run}
        disabled={busy}
        title={title}
        className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-2.5 py-1 text-xs font-medium text-white transition-opacity disabled:opacity-50"
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Play className="h-3.5 w-3.5" />
        )}
        {busy ? busyLabel : label}
      </button>
      {message && (
        <span
          className={
            failed
              ? "text-xs text-[var(--red)]"
              : "text-xs text-[var(--ink-3)]"
          }
        >
          {message}
        </span>
      )}
    </span>
  );
}
