"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { Check, Pencil } from "lucide-react";
import { correctAppliedCaptureAction } from "@/lib/actions";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";

/**
 * Decline-and-edit for captures G2 already filed.
 *
 * The two-tier verifier auto-approves most captures, so a misclassification is
 * usually discovered after the Task/Note/Resource exists. Correcting here
 * soft-archives the wrong entity (never deletes) and teaches the classifier:
 * every correction is logged as a tendency the next triage prompt reads.
 */

const KINDS = [
  { value: "task", label: "Task" },
  { value: "note", label: "Note" },
  { value: "resource", label: "Resource" },
] as const;

const CONTEXTS = [
  "office", "lab", "computer", "phone", "home", "errand",
  "anywhere", "creative", "routine",
];

export type OrganizedCapture = {
  inboxItemId: string;
  title: string;
  rawText: string;
  filedAs: string | null;
  destinationPath: string | null;
  confidence: number | null;
  completedAt: string | Date;
};

export function OrganizedCaptures({ items }: { items: OrganizedCapture[] }) {
  if (items.length === 0) return null;
  return (
    <section className="mt-8">
      <h2 className="text-sm font-semibold text-[var(--ink)]">
        Recently organized by G2
      </h2>
      <p className="mt-0.5 text-xs text-[var(--ink-3)]">
        Filed automatically. Wrong call? Correct it — the original is archived,
        not deleted, and G2 learns the pattern.
      </p>
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <OrganizedRow key={item.inboxItemId} item={item} />
        ))}
      </ul>
    </section>
  );
}

function OrganizedRow({ item }: { item: OrganizedCapture }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"task" | "note" | "resource">(
    item.filedAs === "task" || item.filedAs === "resource" ? item.filedAs : "note",
  );
  const [title, setTitle] = useState(item.title);
  const [context, setContext] = useState("");
  const [dueDate, setDueDate] = useState("");

  const save = () =>
    start(async () => {
      setError(null);
      try {
        await correctAppliedCaptureAction(item.inboxItemId, {
          kind,
          title,
          details: item.rawText,
          context: context || null,
          dueDate: dueDate || null,
        });
        setEditing(false);
        router.refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });

  const unchanged = kind === item.filedAs && title.trim() === item.title.trim();

  return (
    <li
      className={cn(
        "rounded-[var(--radius-card)] border bg-[var(--surface)] p-3",
        pending && "opacity-50",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-[var(--ink)]">
            {item.title}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-[var(--ink-3)]">
            <Badge tone="accent">{item.filedAs ?? "filed"}</Badge>
            {item.confidence != null && (
              <span>· {Math.round(item.confidence * 100)}% confidence</span>
            )}
            <span>
              ·{" "}
              {formatDistanceToNow(new Date(item.completedAt), {
                addSuffix: true,
              })}
            </span>
            {item.destinationPath && (
              <span className="max-w-full truncate font-mono text-[11px]">
                {item.destinationPath}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={() => setEditing((v) => !v)}
          disabled={pending}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1 text-xs font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--accent-soft)] hover:text-[var(--accent-ink)] disabled:opacity-50"
        >
          <Pencil className="h-3.5 w-3.5" />
          {editing ? "Cancel" : "Not right"}
        </button>
      </div>

      {editing && (
        <div className="mt-2.5 rounded-[var(--radius-sm)] border bg-[var(--bg)] p-2.5">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-[var(--ink-3)]">
              Should be
              <select
                value={kind}
                onChange={(e) =>
                  setKind(e.target.value as "task" | "note" | "resource")
                }
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
              >
                {KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-[var(--ink-3)]">
              Title
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
              />
            </label>
            <label className="text-xs text-[var(--ink-3)]">
              Context
              <select
                value={context}
                onChange={(e) => setContext(e.target.value)}
                disabled={kind !== "task"}
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)] disabled:opacity-50"
              >
                <option value="">No context</option>
                {CONTEXTS.map((c) => (
                  <option key={c} value={c}>
                    @{c}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-[var(--ink-3)]">
              Due date
              <input
                type="date"
                value={dueDate}
                onChange={(e) => setDueDate(e.target.value)}
                disabled={kind !== "task"}
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)] disabled:opacity-50"
              />
            </label>
          </div>
          {error && (
            <p className="mt-2 text-xs text-[var(--red)]">{error}</p>
          )}
          <div className="mt-2 flex items-center justify-between gap-3">
            <p className="text-[11px] text-[var(--ink-3)]">
              The current {item.filedAs ?? "entry"} is archived, not deleted.
            </p>
            <button
              onClick={save}
              disabled={pending || !title.trim() || unchanged}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50"
              title={unchanged ? "Change something first" : undefined}
            >
              <Check className="h-3.5 w-3.5" />
              Save and teach G2
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
