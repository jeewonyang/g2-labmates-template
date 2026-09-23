"use client";

import { useState, useTransition } from "react";
import { Loader2 } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/primitives";
import { Input, Select } from "@/components/ui/inputs";
import { TASK_CONTEXTS, TASK_CONTEXT_META, type TaskContext } from "@/lib/types";
import { createProposedTasksAction } from "@/lib/actions";
import type { TaskCandidate } from "@/lib/services/taskExtract";

export type ExtractTarget = {
  /** Status the created tasks land in — `scheduled` for a day plan, `next` for priorities. */
  status: "scheduled" | "next";
  /** ISO date to schedule to, when the source is tied to a day. */
  scheduledDate?: string | null;
};

type Row = TaskCandidate & { include: boolean };

/** What a custom submit receives: the kept rows, as edited. */
export type ExtractedRow = Pick<TaskCandidate, "key" | "title" | "context" | "projectId"> & {
  dueDate: string | null;
};

/**
 * Review-and-create preview for tasks parsed out of free text.
 *
 * Shared deliberately by the daily note and a review's "Next priorities" —
 * they are one affordance ("turn what I wrote into real tasks"), and a second
 * variant of it is exactly what this codebase keeps paying for elsewhere.
 *
 * Duplicates are shown but unchecked rather than hidden: silently dropping a
 * line they can see in their note reads as the parser losing it.
 */
export function TaskExtractDialog({
  open,
  onClose,
  title,
  candidates,
  projects,
  target,
  onCreated,
  dated = false,
  showProject = true,
  intro,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  candidates: TaskCandidate[];
  projects: Array<{ id: string; title: string }>;
  target: ExtractTarget;
  onCreated?: (count: number) => void;
  /** Show an editable due date per row (an application plan's milestones). */
  dated?: boolean;
  /** Hide the per-row project picker when the caller decides the project. */
  showProject?: boolean;
  /** Replaces the default "Completed lines are skipped" hint. */
  intro?: React.ReactNode;
  /**
   * Create the kept rows through the caller's own action (which may add
   * markers or a project). Returns the number created. Default: the plain
   * proposed-tasks action.
   */
  onSubmit?: (rows: ExtractedRow[]) => Promise<number>;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    candidates.map((c) => ({ ...c, include: !c.duplicate })),
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const patch = (key: string, next: Partial<Row>) =>
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...next } : r)));

  const chosen = rows.filter((r) => r.include && r.title.trim());

  const create = () =>
    start(async () => {
      setError(null);
      try {
        const created = onSubmit
          ? await onSubmit(
              chosen.map((r) => ({
                key: r.key,
                title: r.title.trim(),
                context: r.context,
                projectId: r.projectId,
                dueDate: r.dueDate ?? null,
              })),
            )
          : (
              await createProposedTasksAction(
                chosen.map((r) => ({
                  title: r.title.trim(),
                  ...(r.description ? { description: r.description } : {}),
                  status: target.status,
                  ...(r.context ? { context: r.context } : {}),
                  projectId: r.projectId,
                  scheduledDate: target.scheduledDate ?? null,
                })),
              )
            ).created;
        onCreated?.(created);
        onClose();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not create the tasks.");
      }
    });

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      error={error}
      footer={
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-[var(--ink-3)]">
            {chosen.length} of {rows.length} selected
          </span>
          <div className="flex gap-2">
            <Button onClick={onClose} disabled={pending}>Cancel</Button>
            <Button variant="primary" onClick={create} disabled={pending || !chosen.length}>
              {pending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create {chosen.length || ""} task{chosen.length === 1 ? "" : "s"}
            </Button>
          </div>
        </div>
      }
    >
      {rows.length === 0 ? (
        <p className="text-sm text-[var(--ink-3)]">
          Nothing new to pull — every open line here already exists as a task.
        </p>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-[var(--ink-3)]">
            {intro ?? "Completed lines are skipped. Edit anything before creating."}
          </p>
          {rows.map((row) => (
            <div
              key={row.key}
              className="rounded-[var(--radius-sm)] border bg-[var(--surface-2)] p-2"
            >
              <div className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={row.include}
                  onChange={(e) => patch(row.key, { include: e.target.checked })}
                  aria-label={`Include "${row.title}"`}
                  className="mt-2 h-4 w-4 shrink-0 accent-[var(--accent)]"
                />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <Input
                    value={row.title}
                    onChange={(e) => patch(row.key, { title: e.target.value })}
                    aria-label="Task title"
                  />
                  <div className="flex flex-wrap items-center gap-1.5">
                    {row.section && (
                      <span className="rounded-full bg-[var(--surface)] px-2 py-0.5 text-[11px] text-[var(--ink-3)]">
                        {dated ? row.section : `@${row.section}`}
                      </span>
                    )}
                    {row.duplicate && (
                      <span className="rounded-full bg-[var(--amber-soft,var(--surface))] px-2 py-0.5 text-[11px] text-[var(--ink-2)]">
                        already a task
                      </span>
                    )}
                    <Select
                      value={row.context ?? ""}
                      onChange={(e) => patch(row.key, { context: e.target.value || null })}
                      aria-label="Context"
                      className="h-8 w-auto py-1 text-xs"
                    >
                      <option value="">No context</option>
                      {TASK_CONTEXTS.map((c) => (
                        <option key={c} value={c}>
                          {TASK_CONTEXT_META[c as TaskContext].label}
                        </option>
                      ))}
                    </Select>
                    {showProject && (
                      <Select
                        value={row.projectId ?? ""}
                        onChange={(e) => patch(row.key, { projectId: e.target.value || null })}
                        aria-label="Project"
                        className="h-8 w-auto py-1 text-xs"
                      >
                        <option value="">No project</option>
                        {projects.map((p) => (
                          <option key={p.id} value={p.id}>{p.title}</option>
                        ))}
                      </Select>
                    )}
                    {dated && (
                      <Input
                        type="date"
                        value={row.dueDate ?? ""}
                        onChange={(e) => patch(row.key, { dueDate: e.target.value || null })}
                        aria-label="Due date"
                        className="h-8 w-auto py-1 text-xs"
                      />
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Dialog>
  );
}
