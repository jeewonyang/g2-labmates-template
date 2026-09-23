"use client";

import { useTransition } from "react";
import Link from "next/link";
import { Check, Star, Trash2 } from "lucide-react";
import { deleteTaskAction, setHighlightAction, toggleTaskAction } from "@/lib/actions";
import { EditTaskButton } from "@/components/forms/EditForms";
import { PriorityBadge } from "@/components/ui/Badge";
import { cn, friendlyDate, isOverdue, missingDetail } from "@/lib/utils";
import { TASK_CONTEXT_META, type TaskContext } from "@/lib/types";

export type TaskItemData = {
  id: string;
  title: string;
  status: string;
  priority: string;
  context: string | null;
  isHighlight: boolean;
  dueDate: Date | string | null;
  scheduledDate: Date | string | null;
  project?: { id: string; title: string } | null;
  area?: { id: string; title: string } | null;
};

export function TaskItem({
  task,
  showProject = true,
  showHighlight = true,
  flagMissing = false,
}: {
  task: TaskItemData;
  showProject?: boolean;
  showHighlight?: boolean;
  flagMissing?: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const done = task.status === "completed";
  const due = task.dueDate ? new Date(task.dueDate) : null;
  const scheduled = task.scheduledDate ? new Date(task.scheduledDate) : null;
  const dueOverdue = !done && isOverdue(due);
  const actionOverdue = !done && isOverdue(scheduled);
  const ctx = task.context && task.context in TASK_CONTEXT_META
    ? TASK_CONTEXT_META[task.context as TaskContext].label
    : task.context;
  const missing = flagMissing ? missingDetail(task) : null;

  return (
    <div
      className={cn(
        "group flex min-w-0 items-center gap-2 py-2 sm:gap-3",
        pending && "opacity-50"
      )}
    >
      <button
        aria-label={done ? "Mark incomplete" : "Mark complete"}
        onClick={() => startTransition(() => void toggleTaskAction(task.id))}
        // Inline style: Tailwind v4 arbitrary border utilities don't generate
        // in this setup (the ring collapses to 0px), so set the border directly.
        style={{
          borderWidth: "2.5px",
          borderStyle: "solid",
          borderColor: done ? "var(--green)" : "var(--ink-2)",
          backgroundColor: done ? "var(--green)" : "var(--surface-2)",
        }}
        className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-white transition-colors"
      >
        {done && <Check className="h-3 w-3" strokeWidth={3} />}
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "truncate text-sm",
              done ? "text-[var(--ink-3)] line-through" : "text-[var(--ink)]"
            )}
          >
            {task.title}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--ink-3)]">
          {showProject && task.project && (
            <Link href={`/projects/${task.project.id}`} className="hover:text-[var(--accent-ink)]">
              {task.project.title}
            </Link>
          )}
          {ctx && <span>· {ctx}</span>}
          {due && (
            <span className={cn(dueOverdue && "font-medium text-[var(--red)]")}>
              · {dueOverdue ? "Overdue due " : "Due "}{friendlyDate(due)}
            </span>
          )}
          {scheduled && (
            <span className={cn(actionOverdue && "font-medium text-[var(--red)]")}>
              · {actionOverdue ? "Overdue action " : "Action "}{friendlyDate(scheduled)}
            </span>
          )}
          {missing && (
            <span className="rounded-full bg-[var(--amber-soft)] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--amber)]">
              {missing}
            </span>
          )}
        </div>
      </div>

      {task.priority !== "medium" && <PriorityBadge priority={task.priority} />}

      {showHighlight && (
        <button
          aria-label={task.isHighlight ? "Remove highlight" : "Set as today's highlight"}
          onClick={() =>
            startTransition(() => void setHighlightAction(task.id, !task.isHighlight))
          }
          className={cn(
            "shrink-0 rounded p-1 transition-opacity",
            task.isHighlight
              ? "text-[var(--amber)]"
              : "text-[var(--ink-3)] opacity-100 hover:bg-[var(--surface-hover)] sm:opacity-0 sm:group-hover:opacity-100"
          )}
        >
          <Star className="h-4 w-4" fill={task.isHighlight ? "currentColor" : "none"} />
        </button>
      )}

      <EditTaskButton task={task} />

      <button
        aria-label="Delete task"
        title="Moves this task to the archive; it remains recoverable"
        onClick={() => {
          if (window.confirm(`Archive "${task.title}"? You can retain its history without showing it in active lists.`)) {
            startTransition(() => void deleteTaskAction(task.id));
          }
        }}
        className={cn(
          "shrink-0 rounded p-1 text-[var(--ink-3)] transition-opacity hover:bg-[var(--surface-hover)] hover:text-[var(--red)] focus-visible:opacity-100",
          "opacity-70 hover:opacity-100"
        )}
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}

export function TaskList({
  tasks,
  showProject = true,
  showHighlight = true,
  flagMissing = false,
}: {
  tasks: TaskItemData[];
  showProject?: boolean;
  showHighlight?: boolean;
  flagMissing?: boolean;
}) {
  return (
    <ul className="divide-y">
      {tasks.map((t) => (
        <li key={t.id}>
          <TaskItem task={t} showProject={showProject} showHighlight={showHighlight} flagMissing={flagMissing} />
        </li>
      ))}
    </ul>
  );
}
