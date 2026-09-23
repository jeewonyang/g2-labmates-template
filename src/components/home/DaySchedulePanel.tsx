"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useRouter } from "next/navigation";
import { format } from "date-fns";
import {
  ArrowRightToLine,
  Coffee,
  Dumbbell,
  Footprints,
  GripVertical,
  LoaderCircle,
  Moon,
  Pill,
  RefreshCw,
  Sunrise,
  Trash2,
  Utensils,
} from "lucide-react";
import { TaskEditDialog } from "@/components/forms/EditForms";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/inputs";
import { Button } from "@/components/ui/primitives";
import { cellTime } from "@/components/home/WeekCalendar";
import {
  archiveTimeEntryAction,
  createTimeEntryAction,
  placeTaskInPlanAction,
  regenerateDayPlanAction,
  updateTimeEntryAction,
} from "@/lib/actions";
import type {
  BlockKind,
  BoardTask,
  DayPlanBoard,
  PlanItem,
  UnplacedReason,
} from "@/lib/services/dayPlan";
import type { TimeEntry } from "@/lib/services/timeLog";
import { cn } from "@/lib/utils";

/**
 * Plan & actual: the day as two columns on one vertical time axis, after the
 * iPhone app "Sync: Plan & Actual" (the owner, 2026-09-17).
 *
 * Left is the suggested plan (dayPlan.ts), drawn to scale: their fixed blocks as
 * tinted bands, work blocks as faint regions, tasks as cards whose height is
 * their estimated length. Right is what they actually did - TimeEntry rows in
 * Prisma - drawn the same way, so the two columns can be read across. A "now"
 * line crosses both.
 *
 * Logging on the Actual side, cheapest first:
 *   - the arrow on any plan card copies it across ("as planned"); an item in
 *     progress is copied up to now, a future one cannot be copied yet;
 *   - with a mouse or pen, drag on empty space to select a span;
 *   - on touch, long-press a spot: the dialog opens with a 30-minute span to
 *     adjust. A touch drag stays a scroll, because a page they read on the
 *     tablet must keep scrolling, and `touch-action` is fixed at pointerdown
 *     so a gesture cannot be reinterpreted midway.
 * Either path opens one dialog, which suggests whatever the plan had in that
 * span, offers today's tasks, or takes free text. Clicking an entry edits it;
 * its Delete archives, never deletes, like every other entity here.
 *
 * The footer states the comparison plainly - logged, of which as planned, and
 * unlogged time since waking - and nothing is inferred: logging time against
 * a task does not complete it, and completing a task elsewhere logs nothing.
 *
 * Tasks the planner could not fit, and tasks added since the plan, are listed
 * under the board and can be DRAGGED onto it (the owner, 2026-09-17). Dropped on
 * Plan, the task gets that time today - the planner's own pin mechanism, the
 * same write the week strip makes - and the plan re-packs around it without
 * losing the morning; dropped on Actual, the log dialog opens prefilled. Plan
 * cards drag the same way with a mouse or pen. On touch the footer rows drag
 * (they are small, so `touch-none` costs nothing) but the cards do not: a card
 * fills the column, and a column they cannot scroll by touch is worse than
 * editing a time in the dialog.
 */

const PX_PER_HOUR = 56;
const PX_PER_MIN = PX_PER_HOUR / 60;
const SNAP_MIN = 5;
const MIN_DRAG_MIN = 10;
const TOUCH_HOLD_MS = 400;
const TOUCH_DEFAULT_MIN = 30;
/** For a dragged task the planner has not yet estimated (added since the plan). */
const UNESTIMATED_MIN = 45;

const BLOCK_ICON: Record<Exclude<BlockKind, "work">, React.ComponentType<{ className?: string }>> = {
  routine: Sunrise,
  transit: Footprints,
  meal: Utensils,
  workout: Dumbbell,
  rest: Moon,
};

/** Background tint per block kind, shared by plan bands and mirrored entries. */
const BLOCK_TINT: Record<BlockKind, string> = {
  routine: "var(--blue-soft)",
  transit: "var(--gray-soft)",
  work: "transparent",
  meal: "var(--amber-soft)",
  workout: "var(--green-soft)",
  rest: "var(--purple-soft)",
};

const UNPLACED_LABEL: Record<UnplacedReason, string> = {
  day_full: "day is at its 8h planning cap",
  no_room: "no window long enough",
  waiting: "waiting on someone else",
};

function hm(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  const h = Math.floor(m / 60);
  const r = m % 60;
  if (h && r) return `${h}h ${r}m`;
  if (h) return `${h}h`;
  return `${r}m`;
}

function toHHMM(min: number): string {
  const m = ((Math.round(min) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

function fromHHMM(value: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!m) return null;
  const h = parseInt(m[1], 10);
  const mm = parseInt(m[2], 10);
  if (h > 23 || mm > 59) return null;
  return h * 60 + mm;
}

function snap(min: number): number {
  return Math.round(min / SNAP_MIN) * SNAP_MIN;
}

/** Local midnight of the plan's day, from its "yyyy-MM-dd". */
function parseDay(date: string): Date {
  const [y, m, d] = date.split("-").map((x) => parseInt(x, 10));
  return new Date(y, m - 1, d);
}

export function RegenerateDayPlanButton({ generatedAt }: { generatedAt: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <span className="flex items-center gap-2">
      <span className="hidden text-[11px] text-[var(--ink-3)] sm:inline">
        plan built {format(new Date(generatedAt), "h:mm a")}
      </span>
      <Button
        variant="ghost"
        size="sm"
        disabled={pending}
        className="text-[var(--accent-ink)]"
        onClick={() =>
          start(async () => {
            await regenerateDayPlanAction();
            router.refresh();
          })
        }
      >
        {pending ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <RefreshCw className="h-3.5 w-3.5" />
        )}
        Regenerate
      </Button>
    </span>
  );
}

// ---------- the entry dialog ----------

type EntryKind = "task" | "block" | "other";

interface EntryDraft {
  id?: string;
  startMin: number;
  endMin: number;
  title: string;
  kind: EntryKind;
  taskId: string | null;
  blockId: string | null;
  note: string;
}

interface Suggestion {
  key: string;
  label: string;
  kind: EntryKind;
  taskId: string | null;
  blockId: string | null;
  title: string;
}

function TimeEntryDialog({
  draft,
  dayStart,
  suggestions,
  taskOptions,
  onClose,
}: {
  draft: EntryDraft;
  dayStart: Date;
  suggestions: Suggestion[];
  taskOptions: { id: string; title: string }[];
  onClose: () => void;
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [form, setForm] = useState(draft);
  const [error, setError] = useState<string | null>(null);
  const editing = Boolean(draft.id);

  const pick = (s: Suggestion) =>
    setForm({ ...form, title: s.title, kind: s.kind, taskId: s.taskId, blockId: s.blockId });

  const save = () => {
    if (form.endMin - form.startMin < 5) {
      setError("End must be at least five minutes after start.");
      return;
    }
    if (!form.title.trim()) {
      setError("Say what it was, or pick one of the suggestions.");
      return;
    }
    const payload = {
      startAt: new Date(dayStart.getTime() + form.startMin * 60_000).toISOString(),
      endAt: new Date(dayStart.getTime() + form.endMin * 60_000).toISOString(),
      title: form.title.trim(),
      kind: form.kind,
      taskId: form.kind === "task" ? form.taskId : null,
      blockId: form.kind === "block" ? form.blockId : null,
      note: form.note.trim() || null,
    };
    start(async () => {
      try {
        if (draft.id) await updateTimeEntryAction(draft.id, payload);
        else await createTimeEntryAction(payload);
        onClose();
        router.refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not save.");
      }
    });
  };

  const remove = () => {
    if (!draft.id) return;
    if (!window.confirm(`Remove "${draft.title}" from today's log? It is archived, not deleted.`)) return;
    start(async () => {
      await archiveTimeEntryAction(draft.id!);
      onClose();
      router.refresh();
    });
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={editing ? "Edit what you did" : "Log what you did"}
      error={error}
      footer={
        <>
          {editing && (
            <Button
              variant="ghost"
              size="sm"
              onClick={remove}
              disabled={pending}
              className="mr-auto text-[var(--red)]"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" onClick={save} disabled={pending}>
            {pending ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="From">
            <Input
              type="time"
              step={300}
              value={toHHMM(form.startMin)}
              onChange={(e) => {
                const v = fromHHMM(e.target.value);
                if (v != null) setForm({ ...form, startMin: v });
              }}
            />
          </Field>
          <Field label="To">
            <Input
              type="time"
              step={300}
              value={toHHMM(form.endMin)}
              onChange={(e) => {
                const v = fromHHMM(e.target.value);
                if (v != null) setForm({ ...form, endMin: v });
              }}
            />
          </Field>
        </div>

        {suggestions.length > 0 && (
          <div>
            <span className="mb-1 block text-xs font-medium text-[var(--ink-2)]">
              The plan had, in this span
            </span>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((s) => {
                const active =
                  form.kind === s.kind &&
                  (s.kind === "task" ? form.taskId === s.taskId : s.kind === "block" ? form.blockId === s.blockId : form.title === s.title);
                return (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => pick(s)}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-xs transition-colors",
                      active
                        ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent-ink)]"
                        : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]",
                    )}
                  >
                    {s.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <Field label="A task">
          <Select
            value={form.kind === "task" && form.taskId ? form.taskId : ""}
            onChange={(e) => {
              const id = e.target.value;
              const t = taskOptions.find((x) => x.id === id);
              if (!t) setForm({ ...form, kind: form.kind === "task" ? "other" : form.kind, taskId: null });
              else setForm({ ...form, kind: "task", taskId: t.id, blockId: null, title: t.title });
            }}
          >
            <option value="">Not a task</option>
            {taskOptions.map((t) => (
              <option key={t.id} value={t.id}>{t.title}</option>
            ))}
          </Select>
        </Field>

        <Field label="What was it">
          <Input
            value={form.title}
            maxLength={200}
            placeholder="Anything: a meeting that ran long, an errand, a walk"
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
        </Field>

        <Field label="Note (optional)">
          <Textarea
            rows={2}
            maxLength={1000}
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
        </Field>
      </div>
    </Dialog>
  );
}

// ---------- the board ----------

export function DayScheduleBoard({ board }: { board: DayPlanBoard }) {
  const { plan, template, tasks, newSince, entries } = board;
  const router = useRouter();
  const [, startMirror] = useTransition();
  const [editingTask, setEditingTask] = useState<BoardTask | null>(null);
  const [draft, setDraft] = useState<EntryDraft | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const planColRef = useRef<HTMLDivElement>(null);
  const actualColRef = useRef<HTMLDivElement>(null);
  const [, startPlace] = useTransition();

  // A task being dragged from the footer lists or from a plan card, with the
  // column and minute under the pointer for the ghost.
  const [taskDrag, setTaskDrag] = useState<{
    taskId: string;
    title: string;
    minutes: number;
    col: "plan" | "actual" | null;
    min: number;
  } | null>(null);
  const taskDragRef = useRef<{
    taskId: string;
    title: string;
    minutes: number;
    pointerId: number;
    startX: number;
    startY: number;
    active: boolean;
  } | null>(null);
  const suppressClickRef = useRef<string | null>(null);

  const dayStart = useMemo(() => parseDay(plan.date), [plan.date]);
  const toMin = (iso: string | Date) =>
    (new Date(iso).getTime() - dayStart.getTime()) / 60_000;

  // Set after mount: the server render has no "now" that matches the client
  // clock, and a mismatched marker is a hydration error.
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  const nowMin = now ? toMin(now) : null;

  // The axis: their template day, widened to whatever the plan or the log has
  // placed outside it, rounded to whole hours.
  const [wakeH, wakeM] = template.wake.split(":").map(Number);
  const [bedH, bedM] = template.bedPrep.split(":").map(Number);
  const wakeMin = wakeH * 60 + wakeM;
  let axisStart = wakeMin;
  let axisEnd = bedH * 60 + bedM;
  for (const it of plan.items) {
    axisStart = Math.min(axisStart, toMin(it.start));
    axisEnd = Math.max(axisEnd, toMin(it.end));
  }
  for (const e of entries) {
    axisStart = Math.min(axisStart, toMin(e.startAt));
    axisEnd = Math.max(axisEnd, toMin(e.endAt));
  }
  axisStart = Math.floor(axisStart / 60) * 60;
  axisEnd = Math.ceil(axisEnd / 60) * 60;
  const totalPx = (axisEnd - axisStart) * PX_PER_MIN;
  const y = (min: number) => (min - axisStart) * PX_PER_MIN;
  const hours: number[] = [];
  for (let h = axisStart; h <= axisEnd; h += 60) hours.push(h);

  // Scroll so the now-line sits a little below the top on first paint.
  useEffect(() => {
    if (nowMin == null || !scrollRef.current) return;
    if (scrollRef.current.dataset.scrolled) return;
    scrollRef.current.dataset.scrolled = "1";
    scrollRef.current.scrollTop = Math.max(0, y(nowMin) - 140);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nowMin == null]);

  const planTasks = plan.items.filter((i): i is Extract<PlanItem, { kind: "task" }> => i.kind === "task");
  const blockById = new Map(template.blocks.map((b) => [b.id, b]));

  const taskOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const t of Object.values(tasks)) if (t.state !== "removed") seen.set(t.id, t.title);
    for (const t of newSince) seen.set(t.id, t.title);
    return [...seen.entries()].map(([id, title]) => ({ id, title })).sort((a, b) => a.title.localeCompare(b.title));
  }, [tasks, newSince]);

  /** Plan items overlapping [a, b), as chips for the dialog. */
  const suggestionsFor = (a: number, b: number): Suggestion[] => {
    const out: Suggestion[] = [];
    for (const it of plan.items) {
      const s = toMin(it.start);
      const e = toMin(it.end);
      if (e <= a || s >= b) continue;
      if (it.kind === "task") {
        const live = tasks[it.taskId];
        out.push({ key: `t:${it.taskId}`, label: live?.title ?? it.title, kind: "task", taskId: it.taskId, blockId: null, title: live?.title ?? it.title });
      } else if (it.kind === "block" && it.blockKind !== "work") {
        out.push({ key: `b:${it.id}`, label: it.label, kind: "block", taskId: null, blockId: it.id, title: it.label });
      } else if (it.kind === "break") {
        out.push({ key: `o:break`, label: "Break", kind: "other", taskId: null, blockId: null, title: "Break" });
      }
    }
    return out;
  };

  const openNew = (a: number, b: number) =>
    setDraft({ startMin: snap(a), endMin: snap(b), title: "", kind: "other", taskId: null, blockId: null, note: "" });

  const openEdit = (e: TimeEntry) =>
    setDraft({
      id: e.id,
      startMin: toMin(e.startAt),
      endMin: toMin(e.endAt),
      title: e.title,
      kind: (e.kind as EntryKind) ?? "other",
      taskId: e.taskId,
      blockId: e.blockId,
      note: e.note ?? "",
    });

  /**
   * "As planned": copy a plan item to the Actual side. An item in progress is
   * copied up to now; one still ahead cannot be copied, because logging time
   * that has not happened is not a record of anything.
   */
  const mirror = (startIso: string, endIso: string, title: string, kind: EntryKind, taskId: string | null, blockId: string | null) => {
    if (nowMin == null) return;
    const s = toMin(startIso);
    const e = Math.min(toMin(endIso), nowMin);
    if (e - s < 5) return;
    startMirror(async () => {
      await createTimeEntryAction({
        startAt: new Date(dayStart.getTime() + s * 60_000).toISOString(),
        endAt: new Date(dayStart.getTime() + e * 60_000).toISOString(),
        title,
        kind,
        taskId,
        blockId,
        note: null,
      });
      router.refresh();
    });
  };

  // ----- drag / long-press to log on the Actual column -----
  const [selecting, setSelecting] = useState<{ a: number; b: number } | null>(null);
  const gesture = useRef<{
    pointerId: number;
    type: string;
    startY: number;
    startMin: number;
    active: boolean;
    timer: number | null;
  } | null>(null);

  const minAt = (el: HTMLElement, clientY: number) => {
    const rect = el.getBoundingClientRect();
    return axisStart + (clientY - rect.top) / PX_PER_MIN;
  };

  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("[data-entry],button")) return;
    const el = e.currentTarget;
    const startMin = snap(minAt(el, e.clientY));
    const g = { pointerId: e.pointerId, type: e.pointerType, startY: e.clientY, startMin, active: false, timer: null as number | null };
    gesture.current = g;
    if (e.pointerType === "touch") {
      g.timer = window.setTimeout(() => {
        if (gesture.current !== g) return;
        gesture.current = null;
        openNew(startMin, startMin + TOUCH_DEFAULT_MIN);
      }, TOUCH_HOLD_MS);
    }
  };

  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    if (!g || g.pointerId !== e.pointerId) return;
    if (g.type === "touch") {
      if (Math.abs(e.clientY - g.startY) > 8 && g.timer != null) {
        window.clearTimeout(g.timer);
        gesture.current = null; // it is a scroll
      }
      return;
    }
    if (!g.active) {
      if (Math.abs(e.clientY - g.startY) < 4) return;
      g.active = true;
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    const cur = snap(minAt(e.currentTarget, e.clientY));
    setSelecting({ a: Math.min(g.startMin, cur), b: Math.max(g.startMin, cur) });
  };

  const onUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    if (!g || g.pointerId !== e.pointerId) return;
    if (g.timer != null) window.clearTimeout(g.timer);
    gesture.current = null;
    if (!g.active) return;
    const cur = snap(minAt(e.currentTarget, e.clientY));
    const a = Math.min(g.startMin, cur);
    const b = Math.max(g.startMin, cur);
    setSelecting(null);
    if (b - a >= MIN_DRAG_MIN) openNew(a, b);
  };

  const onCancel = () => {
    const g = gesture.current;
    if (g?.timer != null) window.clearTimeout(g.timer);
    gesture.current = null;
    setSelecting(null);
  };

  // ----- dragging a task onto a column -----
  /** Which column and minute a point is over, or null when outside both. */
  const locate = (clientX: number, clientY: number): { col: "plan" | "actual"; min: number } | null => {
    for (const [col, ref] of [["plan", planColRef], ["actual", actualColRef]] as const) {
      const r = ref.current?.getBoundingClientRect();
      if (!r || clientX < r.left || clientX > r.right) continue;
      const raw = axisStart + (clientY - r.top) / PX_PER_MIN;
      return { col, min: snap(Math.max(axisStart, Math.min(axisEnd - SNAP_MIN, raw))) };
    }
    return null;
  };

  /** Nudge the timeline when the pointer nears its top or bottom edge. */
  const autoScroll = (clientY: number) => {
    const el = scrollRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (clientY < r.top + 40) el.scrollTop -= 10;
    else if (clientY > r.bottom - 40) el.scrollTop += 10;
  };

  const beginTaskDrag = (
    e: ReactPointerEvent<HTMLElement>,
    task: { id: string; title: string; minutes: number },
    allowTouch: boolean,
  ) => {
    if (e.button !== 0) return;
    if (e.pointerType === "touch" && !allowTouch) return;
    taskDragRef.current = {
      taskId: task.id,
      title: task.title,
      minutes: task.minutes,
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      active: false,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const moveTaskDrag = (e: ReactPointerEvent<HTMLElement>) => {
    const g = taskDragRef.current;
    if (!g || g.pointerId !== e.pointerId) return;
    if (!g.active) {
      if (Math.hypot(e.clientX - g.startX, e.clientY - g.startY) < 6) return;
      g.active = true;
    }
    autoScroll(e.clientY);
    const at = locate(e.clientX, e.clientY);
    setTaskDrag({ taskId: g.taskId, title: g.title, minutes: g.minutes, col: at?.col ?? null, min: at?.min ?? axisStart });
  };

  const endTaskDrag = (e: ReactPointerEvent<HTMLElement>) => {
    const g = taskDragRef.current;
    if (!g || g.pointerId !== e.pointerId) return;
    taskDragRef.current = null;
    if (!g.active) return; // a plain click; the onClick handles it
    // The click that follows a drop must not open the editor.
    suppressClickRef.current = g.taskId;
    window.setTimeout(() => {
      if (suppressClickRef.current === g.taskId) suppressClickRef.current = null;
    }, 0);
    const at = locate(e.clientX, e.clientY);
    setTaskDrag(null);
    if (!at) return;
    if (at.col === "plan") {
      startPlace(async () => {
        await placeTaskInPlanAction({
          taskId: g.taskId,
          startAt: new Date(dayStart.getTime() + at.min * 60_000).toISOString(),
        });
        router.refresh();
      });
    } else {
      setDraft({
        startMin: at.min,
        endMin: Math.min(axisEnd, at.min + g.minutes),
        title: g.title,
        kind: "task",
        taskId: g.taskId,
        blockId: null,
        note: "",
      });
    }
  };

  const cancelTaskDrag = () => {
    taskDragRef.current = null;
    setTaskDrag(null);
  };

  const clickUnlessDragged = (taskId: string, open: () => void) => {
    if (suppressClickRef.current === taskId) {
      suppressClickRef.current = null;
      return;
    }
    open();
  };

  const ghost = (col: "plan" | "actual") =>
    taskDrag?.col === col ? (
      <div
        className="pointer-events-none absolute left-1 right-1 z-40 overflow-hidden rounded-[var(--radius-sm)] border border-dashed border-[var(--accent)] bg-[var(--accent-soft)] px-1.5 py-0.5 text-[10px] text-[var(--accent-ink)]"
        style={{ top: y(taskDrag.min), height: Math.max(14, taskDrag.minutes * PX_PER_MIN) }}
      >
        <span className="block truncate">
          {cellTime(new Date(dayStart.getTime() + taskDrag.min * 60_000))} · {hm(taskDrag.minutes)} · {taskDrag.title}
        </span>
        <span className="block truncate opacity-80">{col === "plan" ? "drop to plan it here" : "drop to log it here"}</span>
      </div>
    ) : null;

  // ----- the comparison -----
  const summary = useMemo(() => {
    let logged = 0;
    let asPlanned = 0;
    const clippedNow = nowMin == null ? axisEnd : Math.min(nowMin, axisEnd);
    const covered: [number, number][] = [];
    for (const e of entries) {
      const s = toMin(e.startAt);
      const t = toMin(e.endAt);
      logged += t - s;
      for (const it of plan.items) {
        const same =
          (it.kind === "task" && e.taskId && it.taskId === e.taskId) ||
          (it.kind === "block" && e.blockId && it.id === e.blockId);
        if (!same) continue;
        asPlanned += Math.max(0, Math.min(t, toMin(it.end)) - Math.max(s, toMin(it.start)));
      }
      const cs = Math.max(s, wakeMin);
      const ce = Math.min(t, clippedNow);
      if (ce > cs) covered.push([cs, ce]);
    }
    covered.sort((p, q) => p[0] - q[0]);
    let union = 0;
    let cursor = -Infinity;
    for (const [s, t] of covered) {
      const from = Math.max(s, cursor);
      if (t > from) union += t - from;
      cursor = Math.max(cursor, t);
    }
    const elapsed = Math.max(0, clippedNow - wakeMin);
    return { logged, asPlanned, unlogged: Math.max(0, elapsed - union), elapsed };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries, plan.items, nowMin, axisEnd, wakeMin]);

  const notFitting = plan.unplaced.filter((u) => u.reason !== "waiting");
  const waiting = plan.unplaced.filter((u) => u.reason === "waiting");
  const doneCount = planTasks.filter((i) => tasks[i.taskId]?.state === "done").length;

  return (
    <div className="space-y-3">
      <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-[var(--ink-3)]">
        <span>
          <span className="font-medium text-[var(--ink-2)]">{hm(plan.plannedMinutes)}</span> planned
          {planTasks.length > 0 && ` · ${doneCount}/${planTasks.length} done`}
        </span>
        <span>
          <span className="font-medium text-[var(--ink-2)]">{hm(summary.logged)}</span> logged
          {summary.logged > 0 && (
            <>
              {" · "}
              <span className="font-medium text-[var(--green)]">{hm(summary.asPlanned)}</span> as planned
            </>
          )}
        </span>
        {nowMin != null && summary.elapsed > 0 && (
          <span>
            <span className={cn("font-medium", summary.unlogged > 60 ? "text-[var(--amber)]" : "text-[var(--ink-2)]")}>
              {hm(summary.unlogged)}
            </span>{" "}
            unlogged since {cellTime(new Date(dayStart.getTime() + wakeMin * 60_000))}
          </span>
        )}
        {notFitting.length > 0 && (
          <span className="text-[var(--amber)]">
            {notFitting.length} {notFitting.length === 1 ? "task doesn't" : "tasks don't"} fit
          </span>
        )}
      </p>

      <div className="overflow-hidden rounded-[var(--radius-sm)] border">
        <div className="grid grid-cols-[2.75rem_1fr_1fr] border-b bg-[var(--surface-2)]/50 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--ink-3)]">
          <div />
          <div className="border-l px-2 py-1.5">Plan</div>
          <div className="border-l px-2 py-1.5">Actual</div>
        </div>
        <div ref={scrollRef} className="max-h-[72vh] overflow-y-auto">
          <div className="relative grid grid-cols-[2.75rem_1fr_1fr]" style={{ height: totalPx }}>
            {/* hour gutter */}
            <div className="relative">
              {hours.map((h) => (
                <span
                  key={h}
                  className="absolute right-1.5 -translate-y-1/2 font-mono text-[10px] tabular-nums text-[var(--ink-3)]"
                  style={{ top: y(h) }}
                >
                  {h === axisStart ? "" : cellTime(new Date(dayStart.getTime() + h * 60_000))}
                </span>
              ))}
            </div>

            {/* plan */}
            <div ref={planColRef} className="relative border-l">
              <HourLines hours={hours} y={y} />
              {ghost("plan")}
              {plan.items.map((it, i) => {
                const top = y(toMin(it.start));
                const height = Math.max(2, (toMin(it.end) - toMin(it.start)) * PX_PER_MIN);
                const past = nowMin != null && toMin(it.end) <= nowMin;
                const canMirror = nowMin != null && Math.min(toMin(it.end), nowMin) - toMin(it.start) >= 5;
                if (it.kind === "block") {
                  const Icon = it.blockKind !== "work" ? BLOCK_ICON[it.blockKind] : null;
                  return (
                    <div
                      key={it.id}
                      className={cn(
                        "group absolute inset-x-0 overflow-hidden px-1.5 text-[11px]",
                        it.blockKind === "work" ? "border-t border-dashed text-[var(--ink-3)]" : "text-[var(--ink-2)]",
                        past && "opacity-55",
                      )}
                      style={{ top, height, background: BLOCK_TINT[it.blockKind] }}
                    >
                      {height >= 18 && it.blockKind === "work" && (
                        // A tag at the right edge, above the cards: a task that
                        // starts on the block's first minute would otherwise
                        // sit exactly on top of the label.
                        <span className="absolute right-1 top-0.5 z-[15] max-w-[45%] truncate rounded bg-[var(--surface)]/90 px-1 text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--ink-3)]">
                          {it.label}
                        </span>
                      )}
                      {height >= 18 && it.blockKind !== "work" && (
                        <span className="flex items-center gap-1 pt-0.5">
                          {Icon && <Icon className="h-3 w-3 shrink-0" />}
                          <span className="truncate">{it.label}</span>
                          <MirrorButton
                            disabled={!canMirror}
                            onClick={() => mirror(it.start, it.end, it.label, "block", null, it.id)}
                          />
                        </span>
                      )}
                    </div>
                  );
                }
                if (it.kind === "task") {
                  const live = tasks[it.taskId];
                  const done = live?.state === "done";
                  const removed = !live || live.state === "removed";
                  return (
                    <div
                      key={it.taskId}
                      className={cn(
                        "group absolute left-1 right-1 z-10 overflow-hidden rounded-[var(--radius-sm)] border bg-[var(--surface)] shadow-[var(--shadow-sm)]",
                        (past || removed) && !done && "opacity-60",
                      )}
                      style={{ top, height, borderLeft: `3px solid ${done ? "var(--green)" : "var(--accent)"}` }}
                    >
                      <button
                        type="button"
                        disabled={removed}
                        onPointerDown={(e) => !removed && beginTaskDrag(e, { id: it.taskId, title: live?.title ?? it.title, minutes: it.minutes }, false)}
                        onPointerMove={moveTaskDrag}
                        onPointerUp={endTaskDrag}
                        onPointerCancel={cancelTaskDrag}
                        onClick={() => clickUnlessDragged(it.taskId, () => live && !removed && setEditingTask(live))}
                        className="flex h-full w-full cursor-grab flex-col items-stretch justify-start px-1.5 py-0.5 text-left hover:bg-[var(--surface-hover)] active:cursor-grabbing"
                      >
                        <span className={cn("block truncate text-xs", done ? "text-[var(--ink-3)] line-through" : "text-[var(--ink)]")}>
                          {live?.title ?? it.title}
                          {removed && " (removed)"}
                        </span>
                        {height >= 34 && (
                          <span className="block truncate text-[10px] text-[var(--ink-3)]">
                            {hm(it.minutes)} · {it.why}
                          </span>
                        )}
                      </button>
                      {!removed && (
                        <span className="absolute bottom-0.5 right-0.5">
                          <MirrorButton
                            disabled={!canMirror}
                            onClick={() => mirror(it.start, it.end, live?.title ?? it.title, "task", it.taskId, null)}
                          />
                        </span>
                      )}
                    </div>
                  );
                }
                if (it.kind === "break") {
                  return (
                    <div
                      key={`break-${i}`}
                      className="absolute inset-x-1 z-[5] flex items-center gap-1 overflow-hidden border-y border-dashed px-1 text-[10px] text-[var(--ink-3)]"
                      style={{ top, height }}
                    >
                      <Coffee className="h-3 w-3 shrink-0" />
                      Break
                    </div>
                  );
                }
                if (it.kind === "reminder") {
                  return (
                    <div
                      key={it.id}
                      className="absolute right-1 z-20 flex max-w-[55%] -translate-y-1/2 items-center gap-1 rounded-full bg-[var(--cyan-soft)] px-1.5 py-px text-[10px] text-[var(--cyan)]"
                      style={{ top }}
                      title={it.label}
                    >
                      <Pill className="h-3 w-3 shrink-0" />
                      <span className="truncate">{it.label}</span>
                    </div>
                  );
                }
                return null;
              })}
            </div>

            {/* actual */}
            <div
              ref={actualColRef}
              className="relative select-none border-l"
              style={{ touchAction: "pan-y", WebkitTouchCallout: "none" } as React.CSSProperties}
              onPointerDown={onDown}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onPointerCancel={onCancel}
              onContextMenu={(e) => e.preventDefault()}
            >
              <HourLines hours={hours} y={y} />
              {ghost("actual")}
              {entries.length === 0 && !selecting && !taskDrag && (
                <p className="pointer-events-none absolute inset-x-2 top-[45%] text-center text-[11px] leading-snug text-[var(--ink-3)]">
                  Drag here to log what you did.
                  <br />
                  Long-press on touch. The arrow on a plan item copies it across.
                </p>
              )}
              {entries.map((e) => {
                const s = toMin(e.startAt);
                const t = toMin(e.endAt);
                const block = e.blockId ? blockById.get(e.blockId) : undefined;
                const tint = e.kind === "task" ? "var(--accent-soft)" : block ? BLOCK_TINT[block.kind] : "var(--gray-soft)";
                const edge = e.kind === "task" ? "var(--accent)" : block ? "var(--ink-3)" : "var(--border-strong)";
                const height = Math.max(2, (t - s) * PX_PER_MIN);
                return (
                  <button
                    key={e.id}
                    type="button"
                    data-entry
                    onClick={() => openEdit(e)}
                    className="absolute left-1 right-1 z-10 flex flex-col items-stretch justify-start overflow-hidden rounded-[var(--radius-sm)] border px-1.5 py-0.5 text-left hover:brightness-110"
                    style={{ top: y(s), height, background: tint, borderLeft: `3px solid ${edge}` }}
                    title={`${cellTime(new Date(e.startAt))} – ${cellTime(new Date(e.endAt))}${e.note ? `\n${e.note}` : ""}`}
                  >
                    <span className="block truncate text-xs text-[var(--ink)]">{e.title}</span>
                    {height >= 34 && (
                      <span className="block truncate text-[10px] text-[var(--ink-3)]">
                        {cellTime(new Date(e.startAt))} · {hm(t - s)}
                      </span>
                    )}
                  </button>
                );
              })}
              {selecting && (
                <div
                  className="pointer-events-none absolute left-1 right-1 z-20 rounded-[var(--radius-sm)] border border-dashed border-[var(--accent)] bg-[var(--accent-soft)] px-1.5 text-[10px] text-[var(--accent-ink)]"
                  style={{ top: y(selecting.a), height: Math.max(2, (selecting.b - selecting.a) * PX_PER_MIN) }}
                >
                  {toHHMM(selecting.a)} – {toHHMM(selecting.b)} · {hm(selecting.b - selecting.a)}
                </div>
              )}
            </div>

            {/* now */}
            {nowMin != null && nowMin >= axisStart && nowMin <= axisEnd && (
              <div className="pointer-events-none absolute left-[2.75rem] right-0 z-30 flex items-center" style={{ top: y(nowMin) }}>
                <span className="-ml-1 h-2 w-2 rounded-full bg-[var(--accent)]" />
                <span className="h-px flex-1 bg-[var(--accent)]" />
              </div>
            )}
          </div>
        </div>
      </div>

      {(notFitting.length > 0 || waiting.length > 0 || newSince.length > 0) && (
        <div className="space-y-2 border-t pt-2">
          {newSince.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--amber)]">
                Added since this plan ({newSince.length})
              </p>
              <ul className="mt-0.5">
                {newSince.map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      onPointerDown={(e) => beginTaskDrag(e, { id: t.id, title: t.title, minutes: UNESTIMATED_MIN }, true)}
                      onPointerMove={moveTaskDrag}
                      onPointerUp={endTaskDrag}
                      onPointerCancel={cancelTaskDrag}
                      onClick={() => clickUnlessDragged(t.id, () => setEditingTask(t))}
                      className="flex w-full cursor-grab touch-none items-center gap-1.5 rounded px-2 py-1 text-left text-sm text-[var(--ink)] hover:bg-[var(--surface-hover)] active:cursor-grabbing"
                    >
                      <GripVertical className="h-3.5 w-3.5 shrink-0 text-[var(--ink-3)]" />
                      <span className="truncate">{t.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <p className="px-2 text-[11px] text-[var(--ink-3)]">
                Drag one onto the board to place it, or press Regenerate to place them all.
              </p>
            </div>
          )}
          {notFitting.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--ink-3)]">
                Doesn&apos;t fit today ({notFitting.length}) · drag onto the board to place anyway
              </p>
              <ul className="mt-0.5">
                {notFitting.map((u) => {
                  const t = tasks[u.taskId];
                  const done = t?.state === "done";
                  return (
                    <li key={u.taskId}>
                      <button
                        type="button"
                        disabled={!t || t.state === "removed"}
                        onPointerDown={(e) => t && beginTaskDrag(e, { id: t.id, title: t.title, minutes: u.minutes }, true)}
                        onPointerMove={moveTaskDrag}
                        onPointerUp={endTaskDrag}
                        onPointerCancel={cancelTaskDrag}
                        onClick={() => clickUnlessDragged(u.taskId, () => t && setEditingTask(t))}
                        className="grid w-full cursor-grab touch-none grid-cols-[auto_1fr_auto] items-center gap-2 rounded px-2 py-1 text-left hover:bg-[var(--surface-hover)] active:cursor-grabbing"
                      >
                        <GripVertical className="h-3.5 w-3.5 shrink-0 text-[var(--ink-3)]" />
                        <span className="min-w-0">
                          <span className={cn("block truncate text-sm", done ? "text-[var(--ink-3)] line-through" : "text-[var(--ink)]")}>
                            {t?.title ?? u.title}
                          </span>
                          <span className="block text-[11px] text-[var(--ink-3)]">{UNPLACED_LABEL[u.reason]}</span>
                        </span>
                        <span className="rounded-full border px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-[var(--ink-2)]">
                          {hm(u.minutes)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          {waiting.length > 0 && (
            <p className="px-2 text-[11px] text-[var(--ink-3)]">
              Waiting on someone else, not planned: {waiting.map((u) => tasks[u.taskId]?.title ?? u.title).join("; ")}
            </p>
          )}
        </div>
      )}

      {editingTask && (
        <TaskEditDialog task={editingTask} open onClose={() => setEditingTask(null)} />
      )}
      {draft && (
        <TimeEntryDialog
          draft={draft}
          dayStart={dayStart}
          suggestions={suggestionsFor(draft.startMin, draft.endMin)}
          taskOptions={taskOptions}
          onClose={() => setDraft(null)}
        />
      )}
    </div>
  );
}

function HourLines({ hours, y }: { hours: number[]; y: (min: number) => number }) {
  return (
    <>
      {hours.map((h) => (
        <div key={h} className="pointer-events-none absolute inset-x-0 border-t" style={{ top: y(h) }} />
      ))}
    </>
  );
}

/** The "as planned" copy control. Disabled until the item has actually started. */
function MirrorButton({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label="Log as done as planned"
      title={disabled ? "Not started yet" : "Log this as done as planned"}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={cn(
        "ml-auto shrink-0 rounded p-0.5 text-[var(--accent-ink)] transition-opacity hover:bg-[var(--surface-hover)]",
        disabled ? "opacity-30" : "opacity-70 hover:opacity-100 sm:opacity-0 sm:group-hover:opacity-100",
      )}
    >
      <ArrowRightToLine className="h-3 w-3" />
    </button>
  );
}
