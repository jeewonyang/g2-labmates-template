"use client";

import { useState } from "react";
import { TaskEditDialog, type EditableTask } from "@/components/forms/EditForms";
import { friendlyDate } from "@/lib/utils";

export type UpcomingTask = EditableTask;

/**
 * The 14-day sidebar list. A row opens the task editor in place, the same way a
 * week-calendar cell does: reading "due Thursday" and wanting to move, reword,
 * or complete it is one motion, and the rows used to be inert text — the only
 * way to act on one was to re-find it in the flat /tasks list.
 *
 * Rows are buttons, not links, so they stay on /today; TaskEditDialog's
 * router.refresh() on save re-renders this page's server component, which is
 * what owns the list.
 */
export function UpcomingList({ tasks }: { tasks: UpcomingTask[] }) {
  const [editing, setEditing] = useState<UpcomingTask | null>(null);

  return (
    <>
      {/* Negative margin keeps the row text aligned with the card's padding
          while the button still has a hoverable box around it. */}
      <ul className="-mx-1.5 space-y-0.5">
        {tasks.map((t) => {
          const when = t.dueDate ?? t.scheduledDate;
          return (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => setEditing(t)}
                title={`Edit "${t.title}"`}
                className="flex w-full items-center justify-between gap-2 rounded-[var(--radius-sm)] px-1.5 py-1 text-left text-sm transition-colors hover:bg-[var(--surface-hover)]"
              >
                <span className="truncate text-[var(--ink-2)]">{t.title}</span>
                <span className="shrink-0 text-xs text-[var(--ink-3)]">
                  {friendlyDate(when ? new Date(when) : null)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {editing && (
        <TaskEditDialog
          key={editing.id}
          task={editing}
          open
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
