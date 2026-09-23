"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function DeleteAllDraftsButton({
  count,
  compact = false,
}: {
  count: number;
  compact?: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (count <= 0) return null;

  async function removeAll() {
    if (
      !window.confirm(
        `Delete all ${count} active draft${count === 1 ? "" : "s"} from Messages & drafts? They will be archived and remain recoverable.`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/secondbrain/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "dismiss_all" }),
      });
      const result = (await response.json().catch(() => ({}))) as {
        error?: string;
        message?: string;
        failed?: unknown[];
      };
      if (!response.ok || result.failed?.length) {
        throw new Error(
          result.error ?? result.message ?? `Request failed (${response.status}).`,
        );
      }
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        onClick={() => void removeAll()}
        disabled={busy}
        title="Archives every active draft; nothing is permanently deleted"
        className={cn(
          "inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-red-300 font-medium text-red-700 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:text-red-300 dark:hover:bg-red-950",
          compact ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-sm",
        )}
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Trash2 className="h-3.5 w-3.5" />
        )}
        {busy
          ? "Deleting…"
          : compact
            ? "Delete all"
            : `Delete all drafts (${count})`}
      </button>
      {error && (
        <span className="max-w-56 text-xs text-[var(--red)]" role="status">
          {error}
        </span>
      )}
    </span>
  );
}
