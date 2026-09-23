"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { addDays, addWeeks, format, isSameDay, isSameMonth, startOfWeek } from "date-fns";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { TaskEditDialog } from "@/components/forms/EditForms";
import {
  TaskCreateDialog,
  type Option,
  type ProjectOption,
} from "@/components/forms/CreateForms";
import { TaskList, type TaskItemData } from "@/components/tasks/TaskItem";
import { Button } from "@/components/ui/primitives";
import {
  getWeekTasksAction,
  moveTaskToCalendarDateAction,
  rescheduleTaskAction,
} from "@/lib/actions";
import { cn, hasTimeOfDay } from "@/lib/utils";
import Link from "next/link";

/**
 * Compact time label for a calendar cell: "2pm" on the hour, else "2:30pm".
 * Exported so the schedule board under this strip spells times the same way.
 */
export function cellTime(date: Date): string {
  return format(date, date.getMinutes() === 0 ? "haaa" : "h:mmaaa");
}

/**
 * Full task rows, not a calendar-only projection: selecting a day renders the
 * same TaskList used everywhere else, which needs the highlight flag and the
 * project/area titles. `TaskItemData` is structurally assignable to
 * `EditableTask`, so the same row still opens the editor.
 */
export type WeekTask = TaskItemData;

const dayKey = (d: Date) => format(d, "yyyy-MM-dd");

/** "Jul 27 – Aug 2" / "Aug 3 – 9" when both ends share a month. */
function weekRangeLabel(start: Date): string {
  const end = addDays(start, 6);
  return `${format(start, "MMM d")} – ${format(end, isSameMonth(start, end) ? "d" : "MMM d")}`;
}

/**
 * Mon–Sun strip of a week's tasks, placed on their due/scheduled day.
 *
 * A cell opens the task editor in place. It used to link to /tasks?view=all,
 * which threw away the day they clicked from and made their find the task again in
 * a flat list just to change its date — the one edit a calendar click implies.
 *
 * The arrows page to other weeks without leaving /today. Only the current week
 * comes from the server render; neighbours are fetched on demand and kept, so
 * paging back and forth costs one query per week rather than one per press.
 * Editing a task in a paged-to week refetches it on close — `router.refresh()`
 * inside the dialog only re-renders the server component, which owns the
 * current week alone.
 */
export function WeekCalendar({
  tasks,
  triage = [],
  triageTotal = 0,
  now = new Date(),
  projects = [],
  areas = [],
}: {
  tasks: WeekTask[];
  /**
   * Active tasks with neither a due date nor an action date — mostly Quick
   * Capture arrivals. They used to live only behind /tasks?view=triage, a tab
   * they never visit; the weekly strip is where new work gets noticed, so the
   * undated tray sits right above it. Drag a pill onto a day to schedule it.
   */
  triage?: WeekTask[];
  triageTotal?: number;
  now?: Date;
  projects?: ProjectOption[];
  areas?: Option[];
}) {
  const [editing, setEditing] = useState<WeekTask | null>(null);
  /** The day whose "+" was pressed, as yyyy-MM-dd. Empty = dialog closed. */
  const [adding, setAdding] = useState("");
  /** The day whose tasks are listed in full below the grid. Empty = none. */
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const [currentTasks, setCurrentTasks] = useState(tasks);
  const [fetched, setFetched] = useState<Record<number, WeekTask[]>>({});
  const [pending, start] = useTransition();
  const [movingTaskId, setMovingTaskId] = useState<string | null>(null);
  const [moveError, setMoveError] = useState("");
  const [dragVisual, setDragVisual] = useState<{
    taskId: string;
    overDay: string | null;
  } | null>(null);
  const dragRef = useRef<{
    task: WeekTask;
    weekOffset: number;
    pointerId: number;
    startX: number;
    startY: number;
    active: boolean;
    overDay: string | null;
  } | null>(null);
  const suppressClickRef = useRef<string | null>(null);
  const [triageTasks, setTriageTasks] = useState(triage);

  useEffect(() => setCurrentTasks(tasks), [tasks]);
  useEffect(() => setTriageTasks(triage), [triage]);

  const weekStart = startOfWeek(addWeeks(now, offset), { weekStartsOn: 1 });
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  const weekTasks = offset === 0 ? currentTasks : (fetched[offset] ?? []);
  const loading = pending && offset !== 0 && fetched[offset] == null;

  /**
   * Anchor mid-week rather than at its first instant: the action re-derives the
   * week from this instant in the server's timezone, and a Monday-00:00 anchor
   * lands in the previous week the moment the two clocks disagree at all.
   */
  const anchorIso = (weeks: number) =>
    addDays(startOfWeek(addWeeks(now, weeks), { weekStartsOn: 1 }), 3).toISOString();

  const load = (next: number, { refresh = false }: { refresh?: boolean } = {}) => {
    setOffset(next);
    if (next === 0 || (fetched[next] != null && !refresh)) return;
    start(async () => {
      try {
        const rows = await getWeekTasksAction(anchorIso(next));
        setFetched((prev) => ({ ...prev, [next]: rows }));
      } catch {
        setFetched((prev) => ({ ...prev, [next]: prev[next] ?? [] }));
      }
    });
  };

  const closeEditor = () => {
    setEditing(null);
    if (offset !== 0) load(offset, { refresh: true });
  };

  const patchWeekTask = (
    weekOffset: number,
    taskId: string,
    patch: (task: WeekTask) => WeekTask,
  ) => {
    if (weekOffset === 0) {
      setCurrentTasks((rows) => rows.map((row) => row.id === taskId ? patch(row) : row));
      return;
    }
    setFetched((weeks) => ({
      ...weeks,
      [weekOffset]: (weeks[weekOffset] ?? []).map((row) =>
        row.id === taskId ? patch(row) : row
      ),
    }));
  };

  const insertIntoWeek = (weekOffset: number, task: WeekTask) => {
    if (weekOffset === 0) {
      setCurrentTasks((rows) => [...rows, task]);
      return;
    }
    setFetched((weeks) => ({
      ...weeks,
      [weekOffset]: [...(weeks[weekOffset] ?? []), task],
    }));
  };

  const removeFromWeek = (weekOffset: number, taskId: string) => {
    if (weekOffset === 0) {
      setCurrentTasks((rows) => rows.filter((row) => row.id !== taskId));
      return;
    }
    setFetched((weeks) => ({
      ...weeks,
      [weekOffset]: (weeks[weekOffset] ?? []).filter((row) => row.id !== taskId),
    }));
  };

  /**
   * Dropping an undated tray task on a day gives it that day as its action
   * date (rescheduleTask also sets status "scheduled", so it lands on Today's
   * lists the way daily-note tasks do). Optimistic like moveTask: the pill
   * jumps from the tray into the cell, and comes back if the write fails.
   */
  const scheduleTriageTask = (task: WeekTask, weekOffset: number, targetDay: string) => {
    const moved = new Date(`${targetDay}T00:00:00`);
    setMoveError("");
    setMovingTaskId(task.id);
    setTriageTasks((rows) => rows.filter((row) => row.id !== task.id));
    insertIntoWeek(weekOffset, { ...task, scheduledDate: moved, status: "scheduled" });

    start(async () => {
      try {
        await rescheduleTaskAction(task.id, moved.toISOString());
      } catch {
        removeFromWeek(weekOffset, task.id);
        setTriageTasks((rows) => [task, ...rows]);
        setMoveError(`Could not schedule “${task.title}”. Please try again.`);
      } finally {
        setMovingTaskId(null);
      }
    });
  };

  const moveTask = (task: WeekTask, weekOffset: number, targetDay: string) => {
    if (!task.dueDate && !task.scheduledDate) {
      scheduleTriageTask(task, weekOffset, targetDay);
      return;
    }
    const field = task.dueDate ? "dueDate" : "scheduledDate";
    const sourceValue = task[field];
    if (!sourceValue || dayKey(new Date(sourceValue)) === targetDay) return;

    const source = new Date(sourceValue);
    const time = format(source, "HH:mm:ss.SSS");
    const moved = new Date(`${targetDay}T${time}`);
    setMoveError("");
    setMovingTaskId(task.id);
    patchWeekTask(weekOffset, task.id, (row) =>
      field === "dueDate"
        ? { ...row, dueDate: moved }
        : { ...row, scheduledDate: moved }
    );

    start(async () => {
      try {
        await moveTaskToCalendarDateAction(task.id, targetDay);
      } catch {
        patchWeekTask(weekOffset, task.id, (row) =>
          field === "dueDate"
            ? { ...row, dueDate: sourceValue }
            : { ...row, scheduledDate: sourceValue }
        );
        setMoveError(`Could not move “${task.title}”. Please try again.`);
      } finally {
        setMovingTaskId(null);
      }
    });
  };

  const dayUnderPointer = (x: number, y: number) =>
    document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-week-day]")
      ?.dataset.weekDay ?? null;

  const startDrag = (event: ReactPointerEvent<HTMLButtonElement>, task: WeekTask) => {
    if (event.button !== 0 || movingTaskId) return;
    dragRef.current = {
      task,
      weekOffset: offset,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      active: false,
      overDay: null,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const continueDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (!drag.active) {
      const distance = Math.hypot(
        event.clientX - drag.startX,
        event.clientY - drag.startY,
      );
      if (distance < 7) return;
      drag.active = true;
    }
    event.preventDefault();
    const overDay = dayUnderPointer(event.clientX, event.clientY);
    if (overDay !== drag.overDay) {
      drag.overDay = overDay;
      setDragVisual({ taskId: drag.task.id, overDay });
    }
  };

  const finishDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setDragVisual(null);
    if (!drag.active) return;

    event.preventDefault();
    suppressClickRef.current = drag.task.id;
    window.setTimeout(() => {
      if (suppressClickRef.current === drag.task.id) suppressClickRef.current = null;
    }, 0);
    const targetDay = dayUnderPointer(event.clientX, event.clientY) ?? drag.overDay;
    if (targetDay) moveTask(drag.task, drag.weekOffset, targetDay);
  };

  const cancelDrag = () => {
    dragRef.current = null;
    setDragVisual(null);
  };

  const onDay = (day: Date) =>
    weekTasks.filter((t) => {
      const date = t.dueDate ?? t.scheduledDate;
      return date != null && isSameDay(new Date(date), day);
    });

  const byDay = days.map(onDay);
  const selectedDay = days.find((d) => dayKey(d) === selected) ?? null;
  const selectedTasks = selectedDay ? onDay(selectedDay) : [];

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Previous week"
            onClick={() => load(offset - 1)}
            className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)] border bg-[var(--surface)] text-[var(--ink-2)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label="Next week"
            onClick={() => load(offset + 1)}
            className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)] border bg-[var(--surface)] text-[var(--ink-2)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)]"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
          <span className="ml-1.5 text-xs font-medium text-[var(--ink-2)]">
            {weekRangeLabel(weekStart)}
          </span>
          <span className="text-[11px] text-[var(--ink-3)]">
            {offset === 0
              ? "· This week"
              : offset === -1
                ? "· Last week"
                : offset === 1
                  ? "· Next week"
                  : `· ${offset > 0 ? "+" : "−"}${Math.abs(offset)} weeks`}
          </span>
        </div>
        {offset !== 0 && (
          <Button size="sm" variant="ghost" onClick={() => load(0)} className="h-7 px-2">
            This week
          </Button>
        )}
      </div>

      <p className="mb-2 text-[11px] text-[var(--ink-3)]">
        Drag a task to another day to move its date.
      </p>

      {/*
        New & undated: Quick Capture tasks that arrived without a date. They
        only existed behind /tasks?view=triage, which is not on the daily
        path — parking them against the week strip means dating one is a drag,
        not a page visit.
      */}
      {triageTasks.length > 0 && (
        <div className="mb-2 rounded-[var(--radius-sm)] border border-dashed border-[var(--amber)] bg-[var(--surface-2)] px-2.5 py-2">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--amber)]">
              New &amp; undated ({triageTotal || triageTasks.length})
            </span>
            <span className="flex items-center gap-2 text-[11px] text-[var(--ink-3)]">
              <span className="hidden sm:inline">Drag onto a day, or click to edit</span>
              {triageTotal > triageTasks.length && (
                <Link
                  href="/tasks?view=triage"
                  className="text-[var(--accent-ink)] hover:underline"
                >
                  All {triageTotal}
                </Link>
              )}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {triageTasks.map((t) => (
              <button
                key={t.id}
                type="button"
                onPointerDown={(event) => startDrag(event, t)}
                onPointerMove={continueDrag}
                onPointerUp={finishDrag}
                onPointerCancel={cancelDrag}
                onClick={() => {
                  if (suppressClickRef.current === t.id) {
                    suppressClickRef.current = null;
                    return;
                  }
                  setEditing(t);
                }}
                aria-grabbed={dragVisual?.taskId === t.id}
                aria-label={`${t.title}. Drag onto a day to schedule it, or click to edit.`}
                title={`${t.title} — drag onto a day to schedule`}
                className={cn(
                  "max-w-full touch-none truncate rounded border-l-2 border-[var(--amber)] bg-[var(--surface)] px-1.5 py-1 text-left text-[11px] leading-tight text-[var(--ink-2)] shadow-[var(--shadow-sm)] transition-colors hover:bg-[var(--surface-hover)] cursor-grab active:cursor-grabbing",
                  dragVisual?.taskId === t.id && "opacity-40",
                  movingTaskId === t.id && "opacity-60"
                )}
              >
                {t.title}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <div
          className={cn(
            "grid min-w-[640px] grid-cols-7 gap-1.5 transition-opacity",
            loading && "opacity-50"
          )}
        >
          {days.map((day, i) => {
            const isToday = isSameDay(day, now);
            const key = dayKey(day);
            const isSelected = key === selected;
            return (
              /*
                The whole cell selects the day — the date text alone was a
                ~24px target on a column that is already a comfortable one.
                The controls inside it (the "+", each task pill) stop
                propagation, so they keep their own meaning.

                A plain div rather than role="button": the cell contains real
                buttons, and claiming the container is also a button would
                nest interactive roles and lie to assistive tech. The date text
                stays a genuine <button>, so the keyboard and screen-reader
                path is unchanged — the cell click is a pointer convenience on
                top of it.
              */
              <div
                key={i}
                data-week-day={key}
                onClick={() => setSelected(isSelected ? "" : key)}
                className={cn(
                  "cursor-pointer rounded-[var(--radius-sm)] border p-2 transition-colors",
                  isSelected
                    ? "border-[var(--accent)] ring-1 ring-[var(--accent)]"
                    : isToday
                      ? "border-[var(--accent)]"
                      : "hover:border-[var(--border-strong)]",
                  isToday ? "bg-[var(--accent-soft)]" : "bg-[var(--surface-2)]",
                  dragVisual?.overDay === key && "ring-2 ring-[var(--accent)]"
                )}
              >
                {/*
                  "Show me this day" and "add to this day" stay separate
                  targets: overloading one control would make the other
                  undiscoverable. The "+" is always visible rather than
                  hover-revealed — /today is read on a tablet, where there is no
                  hover.
                */}
                <div className="mb-1.5 flex items-center justify-between gap-1">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelected(isSelected ? "" : key);
                    }}
                    aria-pressed={isSelected}
                    title={`Show tasks on ${format(day, "EEEE, MMM d")}`}
                    className={cn(
                      "-mx-1 rounded px-1 text-xs font-semibold transition-colors",
                      isToday ? "text-[var(--accent-ink)]" : "text-[var(--ink-3)]",
                      isSelected && "text-[var(--accent-ink)] underline"
                    )}
                  >
                    {format(day, "EEE")}{" "}
                    <span className="font-normal">{format(day, "d")}</span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setAdding(key);
                    }}
                    aria-label={`New task on ${format(day, "EEEE, MMM d")}`}
                    title={`New task on ${format(day, "EEEE, MMM d")}`}
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[var(--ink-3)] opacity-70 transition-opacity hover:bg-[var(--surface-hover)] hover:text-[var(--accent-ink)] hover:opacity-100"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="space-y-1">
                  {byDay[i].length === 0 ? (
                    <div className="text-[11px] text-[var(--ink-3)] opacity-60">—</div>
                  ) : (
                    byDay[i].map((t) => {
                      const done = t.status === "completed";
                      const placed = t.dueDate ?? t.scheduledDate;
                      const time = placed && hasTimeOfDay(new Date(placed)) ? cellTime(new Date(placed)) : null;
                      return (
                        <button
                          key={t.id}
                          type="button"
                          onPointerDown={(event) => startDrag(event, t)}
                          onPointerMove={continueDrag}
                          onPointerUp={finishDrag}
                          onPointerCancel={cancelDrag}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (suppressClickRef.current === t.id) {
                              suppressClickRef.current = null;
                              return;
                            }
                            setEditing(t);
                          }}
                          aria-grabbed={dragVisual?.taskId === t.id}
                          aria-label={`${t.title}. Drag to another day or click to edit.`}
                          title={`${time ? `${time} · ` : ""}${t.title} — drag to move`}
                          className={cn(
                            "block w-full touch-none truncate rounded border-l-2 bg-[var(--surface)] px-1.5 py-1 text-left text-[11px] leading-tight shadow-[var(--shadow-sm)] transition-colors hover:bg-[var(--surface-hover)] cursor-grab active:cursor-grabbing",
                            done
                              ? "border-[var(--green)] text-[var(--ink-3)] line-through"
                              : t.priority === "urgent"
                                ? "border-[var(--red)] text-[var(--ink)]"
                                : t.priority === "high"
                                  ? "border-[var(--amber)] text-[var(--ink)]"
                                  : "border-[var(--border-strong)] text-[var(--ink-2)]",
                            dragVisual?.taskId === t.id && "opacity-40",
                            movingTaskId === t.id && "opacity-60"
                          )}
                        >
                          {time && <span className="font-semibold">{time} </span>}
                          {t.title}
                        </button>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {moveError && (
        <p role="alert" className="mt-2 text-xs text-[var(--red)]">
          {moveError}
        </p>
      )}

      {/*
        The grid cells are one truncated line each — enough to see that a day
        is busy, not enough to act on. Selecting a day renders the same rows the
        rest of the app uses, so completing, starring, editing, and archiving
        are all available without leaving /today.
      */}
      {selectedDay && (
        <div className="mt-3 rounded-[var(--radius-sm)] border bg-[var(--surface-2)] p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold text-[var(--ink)]">
              {format(selectedDay, "EEEE, MMMM d")}
              <span className="ml-1.5 font-normal text-[var(--ink-3)]">
                {selectedTasks.length} task{selectedTasks.length === 1 ? "" : "s"}
              </span>
            </h3>
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="secondary"
                className="h-7 px-2"
                onClick={() => setAdding(dayKey(selectedDay))}
              >
                <Plus className="h-3.5 w-3.5" />
                New task
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2"
                onClick={() => setSelected("")}
              >
                Close
              </Button>
            </div>
          </div>
          {selectedTasks.length ? (
            <TaskList tasks={selectedTasks} />
          ) : (
            <p className="py-1 text-sm text-[var(--ink-3)]">
              Nothing on this day yet.
            </p>
          )}
        </div>
      )}

      {editing && (
        <TaskEditDialog
          key={editing.id}
          task={editing}
          open
          onClose={closeEditor}
        />
      )}

      <TaskCreateDialog
        open={adding !== ""}
        onClose={() => {
          setAdding("");
          // A paged-to week is client-side state that router.refresh() does not
          // own, so re-pull it once the new task exists.
          if (offset !== 0) load(offset, { refresh: true });
        }}
        projects={projects}
        areas={areas}
        defaultDueDate={adding}
        dateLabel={adding ? format(new Date(`${adding}T00:00:00`), "EEE, MMM d") : undefined}
      />
    </div>
  );
}
