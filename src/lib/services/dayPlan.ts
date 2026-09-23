import { promises as fs } from "node:fs";
import path from "node:path";
import { endOfDay, format, startOfDay } from "date-fns";
import { db } from "@/lib/db";
import { hasTimeOfDay } from "@/lib/utils";
import { PRIORITY_META, type Priority } from "@/lib/types";
import { getTodayTasks, rescheduleTask } from "@/lib/services/tasks";
import { listTimeEntries, type TimeEntry } from "@/lib/services/timeLog";

/**
 * The suggested daily schedule under the week strip on /today.
 *
 * Two halves. The pure half (`estimateMinutes`, `buildDayPlan`) takes their day
 * template plus today's open tasks and packs the tasks into the work blocks,
 * inferring a duration for each from its content. The I/O half stores the
 * result under `.claude/data/state/day-plan.json` and reconciles it with the
 * live task table on every render.
 *
 * Why store it at all: a plan recomputed on every page load would reshuffle
 * under them as they read, and "Regenerate" would mean nothing. The stored plan
 * is the one they agreed to look at; completions and removals are overlaid
 * from the live table, and tasks captured since are counted as "new since
 * this plan" until they press Regenerate. A new calendar day regenerates on
 * first view, so the 06:00 planning hour starts from a fresh board.
 *
 * Why no model: the day is fixed arithmetic around their blocks, and the
 * duration signal in a task title is mostly its leading verb. A rule-based
 * estimate is instant (the button is pressed at 06:05, on a tablet), never
 * waits on a subscription window, and is testable. `estimateMinutes` is the
 * one function to replace if a model ever proves better at it.
 *
 * The day template is `.claude/agents/day-schedule.json` (2026-09-16), the
 * same file `setup_scheduler.ps1` and `heartbeat.py` read: their day is written
 * down once, and everything that depends on it follows.
 */

const REPO = process.cwd();
const TEMPLATE_FILE = path.join(REPO, ".claude", "agents", "day-schedule.json");
const PLAN_FILE = path.join(REPO, ".claude", "data", "state", "day-plan.json");

// ---------- template ----------

export type BlockKind = "routine" | "transit" | "work" | "meal" | "workout" | "rest";
export type WorkMode = "focus" | "light";

export interface DayBlock {
  id: string;
  kind: BlockKind;
  /** Work blocks only. `light` takes short tasks only (email, reading). */
  mode?: WorkMode;
  label: string;
  /** "HH:mm", local. */
  start: string;
  end: string;
  hint?: string;
}

/** A one-line nudge pinned to a block's start or end: supplements, water. */
export interface DayReminder {
  id: string;
  block: string;
  when: "start" | "end";
  label: string;
}

export interface DayTemplate {
  timezone: string;
  wake: string;
  dayEnd: string;
  bedPrep: string;
  sleepTargetHours: number;
  blocks: DayBlock[];
  reminders: DayReminder[];
  planning: {
    maxPlannedTaskHours: number;
    focusBreakAfterMinutes: number;
    breakMinutes: number;
    lightMaxTaskMinutes: number;
  };
}

/**
 * The shipped default day, used only if the JSON is missing or unreadable so
 * the board never blanks. Keep it identical to the file; the file wins.
 */
export const DEFAULT_TEMPLATE: DayTemplate = {
  timezone: "America/Los_Angeles",
  wake: "07:00",
  dayEnd: "20:00",
  bedPrep: "22:30",
  sleepTargetHours: 8,
  blocks: [
    { id: "morning", kind: "routine", label: "Plan the day, breakfast", start: "07:00", end: "08:00" },
    { id: "commute", kind: "transit", label: "Get ready, head to lab", start: "08:00", end: "08:45" },
    { id: "settle", kind: "routine", label: "Settle in", start: "08:45", end: "09:00" },
    { id: "morning_work", kind: "work", mode: "focus", label: "Deep work", start: "09:00", end: "12:00" },
    { id: "lunch", kind: "meal", label: "Lunch", start: "12:00", end: "13:00" },
    { id: "afternoon_work", kind: "work", mode: "focus", label: "Afternoon work", start: "13:00", end: "18:00" },
    { id: "dinner", kind: "meal", label: "Dinner", start: "18:00", end: "19:00" },
    { id: "evening_work", kind: "work", mode: "light", label: "Light work", start: "19:00", end: "20:00" },
    { id: "wind_down", kind: "rest", label: "Free time", start: "20:00", end: "22:30" },
  ],
  reminders: [],
  planning: {
    maxPlannedTaskHours: 8,
    focusBreakAfterMinutes: 90,
    breakMinutes: 10,
    lightMaxTaskMinutes: 30,
  },
};

const BLOCK_KINDS: BlockKind[] = ["routine", "transit", "work", "meal", "workout", "rest"];
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

function num(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

/** Parse the JSON leniently: one bad block drops that block, not the board. */
export function parseTemplate(raw: unknown): DayTemplate {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const blocks: DayBlock[] = Array.isArray(r.blocks)
    ? (r.blocks as unknown[]).flatMap((b) => {
        const x = (b && typeof b === "object" ? b : {}) as Record<string, unknown>;
        const kind = BLOCK_KINDS.includes(x.kind as BlockKind) ? (x.kind as BlockKind) : null;
        if (
          !kind ||
          typeof x.id !== "string" ||
          typeof x.start !== "string" ||
          typeof x.end !== "string" ||
          !HHMM.test(x.start) ||
          !HHMM.test(x.end) ||
          x.start >= x.end
        ) {
          return [];
        }
        return [
          {
            id: x.id,
            kind,
            ...(kind === "work" ? { mode: x.mode === "light" ? ("light" as const) : ("focus" as const) } : {}),
            label: typeof x.label === "string" ? x.label : x.id,
            start: x.start,
            end: x.end,
            ...(typeof x.hint === "string" && x.hint ? { hint: x.hint } : {}),
          },
        ];
      })
    : [];
  const finalBlocks = blocks.length ? blocks.sort((a, b) => a.start.localeCompare(b.start)) : DEFAULT_TEMPLATE.blocks;
  const blockIds = new Set(finalBlocks.map((b) => b.id));
  const reminders: DayReminder[] = Array.isArray(r.reminders)
    ? (r.reminders as unknown[]).flatMap((x) => {
        const y = (x && typeof x === "object" ? x : {}) as Record<string, unknown>;
        if (
          typeof y.id !== "string" ||
          typeof y.block !== "string" ||
          !blockIds.has(y.block) ||
          (y.when !== "start" && y.when !== "end") ||
          typeof y.label !== "string"
        ) {
          return [];
        }
        return [{ id: y.id, block: y.block, when: y.when, label: y.label }];
      })
    : [];
  const planning = (r.planning && typeof r.planning === "object" ? r.planning : {}) as Record<string, unknown>;
  const d = DEFAULT_TEMPLATE;
  return {
    timezone: typeof r.timezone === "string" ? r.timezone : d.timezone,
    wake: typeof r.wake === "string" && HHMM.test(r.wake) ? r.wake : d.wake,
    dayEnd: typeof r.day_end === "string" && HHMM.test(r.day_end) ? r.day_end : d.dayEnd,
    bedPrep: typeof r.bed_prep === "string" && HHMM.test(r.bed_prep) ? r.bed_prep : d.bedPrep,
    sleepTargetHours: num(r.sleep_target_hours, d.sleepTargetHours),
    blocks: finalBlocks,
    // An explicit empty list is respected: they can switch reminders off.
    reminders: Array.isArray(r.reminders) ? reminders : d.reminders,
    planning: {
      maxPlannedTaskHours: num(planning.max_planned_task_hours, d.planning.maxPlannedTaskHours),
      focusBreakAfterMinutes: num(planning.focus_break_after_minutes, d.planning.focusBreakAfterMinutes),
      breakMinutes: num(planning.break_minutes, d.planning.breakMinutes),
      lightMaxTaskMinutes: num(planning.light_max_task_minutes, d.planning.lightMaxTaskMinutes),
    },
  };
}

export async function loadDayTemplate(): Promise<DayTemplate> {
  try {
    return parseTemplate(JSON.parse(await fs.readFile(TEMPLATE_FILE, "utf8")));
  } catch {
    return DEFAULT_TEMPLATE;
  }
}

// ---------- duration inference ----------

export type EstimateBasis = "stated" | "keyword" | "context" | "default";

export interface Estimate {
  minutes: number;
  basis: EstimateBasis;
  /** Short human reason: "stated", "writing", "quick reply", "default". */
  label: string;
}

/**
 * Keyword tiers, checked against the title. The EARLIEST match in the title
 * wins, because English imperative titles lead with the verb and the verb is
 * the duration signal: "Email Dr. Advisor about the manuscript" is a 15-minute
 * email, not a two-hour manuscript. Korean tokens are substring-matched (no
 * word boundaries in Korean); English tokens need boundaries so "plan" does
 * not match "planning"'s cousin "plant".
 */
const TIERS: { minutes: number; label: string; words: string[]; ko: string[] }[] = [
  {
    minutes: 15,
    label: "quick",
    words: [
      "email", "e-mail", "reply", "respond", "send", "forward", "ask", "ping", "message", "text",
      "call", "book", "order", "confirm", "rsvp", "register", "sign", "pay", "print", "upload",
      "download", "rename", "follow up", "follow-up", "check in", "remind", "invite", "share",
      "schedule", "reschedule", "cancel", "approve", "reserve", "renew", "file", "log",
    ],
    ko: ["이메일", "메일", "답장", "회신", "전화", "확인", "예약", "신청", "등록", "공유", "전달"],
  },
  {
    minutes: 30,
    label: "short",
    words: [
      "review", "read", "skim", "check", "look over", "look at", "proofread", "update", "edit",
      "outline", "plan", "organize", "organise", "clean", "tidy", "summarize", "summarise", "notes",
      "triage", "sort", "list", "compare", "pick", "choose", "decide", "brainstorm", "sketch",
      "order supplies", "inventory", "label", "aliquot", "thaw", "passage",
    ],
    ko: ["읽기", "읽다", "검토", "정리", "확인하기", "요약", "계획", "수정", "리뷰", "체크"],
  },
  {
    minutes: 60,
    label: "meeting, prep, or fixing",
    words: [
      "meeting", "meet", "1:1", "one-on-one", "discuss", "seminar", "talk", "lecture", "journal club",
      "lab meeting", "group meeting", "present", "presentation", "prep", "prepare", "practice",
      "rehearse", "debug", "fix", "install", "set up", "setup", "configure", "troubleshoot",
      "figure out", "plot", "figure", "calibrate", "train", "teach", "tutorial", "interview",
      "office hours", "workshop", "call with", "sync", "onboard",
    ],
    ko: ["회의", "미팅", "세미나", "발표", "준비", "연습", "토론", "강의", "디버그"],
  },
  {
    minutes: 120,
    label: "writing, analysis, or bench work",
    words: [
      "write", "writing", "draft", "manuscript", "paper", "proposal", "grant", "fellowship",
      "application", "essay", "statement", "abstract", "poster", "slides", "deck", "analyze",
      "analyse", "analysis", "code", "implement", "build", "script", "pipeline", "model",
      "simulate", "protocol", "experiment", "culture", "transfect", "transfection", "pcr",
      "gel", "western", "blot", "imaging", "microscopy", "image", "purify", "purification",
      "clone", "cloning", "assay", "prep samples", "sample prep", "sequencing", "design",
      "run", "dissect", "inject", "harvest", "stain", "sonicate", "flow", "facs", "elisa",
      "revise", "revision", "rewrite", "literature", "lit review", "benchmark", "optimize",
      "optimise", "data", "results", "quantify",
    ],
    ko: ["작성", "초안", "논문", "제안서", "실험", "분석", "코딩", "구현", "디자인", "설계", "발표자료", "포스터", "수정본", "리라이팅"],
  },
];

const TIER_BY_CONTEXT: Record<string, { minutes: number; label: string }> = {
  phone: { minutes: 15, label: "phone" },
  routine: { minutes: 20, label: "routine" },
  errand: { minutes: 45, label: "errand" },
  creative: { minutes: 120, label: "deep work" },
};

const DEFAULT_MINUTES = 45;
export const MIN_TASK_MINUTES = 10;
export const MAX_TASK_MINUTES = 180;

/** "2h", "1.5 hr", "90 min", "1h 30m" anywhere in the text, summed. */
export function statedMinutes(text: string): number | null {
  const t = text.toLowerCase();
  let total = 0;
  let found = false;
  for (const m of t.matchAll(/(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\b/g)) {
    total += Math.round(parseFloat(m[1]) * 60);
    found = true;
  }
  for (const m of t.matchAll(/(\d+)\s*(minutes?|mins?|m)\b/g)) {
    total += parseInt(m[1], 10);
    found = true;
  }
  // Korean: 2시간, 30분
  for (const m of t.matchAll(/(\d+(?:\.\d+)?)\s*시간/g)) {
    total += Math.round(parseFloat(m[1]) * 60);
    found = true;
  }
  for (const m of t.matchAll(/(\d+)\s*분(?!야|류|석|자)/g)) {
    total += parseInt(m[1], 10);
    found = true;
  }
  return found && total > 0 ? total : null;
}

function roundTo5(n: number): number {
  return Math.max(MIN_TASK_MINUTES, Math.min(MAX_TASK_MINUTES, Math.round(n / 5) * 5));
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Position of the earliest tier keyword in the title, per tier. Word-boundary
 * for English; substring for Korean.
 */
function earliestMatch(title: string, tier: (typeof TIERS)[number]): number {
  let best = Infinity;
  for (const w of tier.words) {
    const re = new RegExp(`(?:^|[^a-z0-9])${escapeRe(w)}(?=$|[^a-z0-9])`, "i");
    const m = re.exec(title);
    if (m && m.index < best) best = m.index;
  }
  for (const k of tier.ko) {
    const i = title.indexOf(k);
    if (i >= 0 && i < best) best = i;
  }
  return best;
}

/**
 * Infer how long a task will take from what it says. Signals in order of
 * trust: a duration written in the text; the leading verb/noun tier of the
 * title; the GTD context; a 45-minute default. Then two modifiers - a long
 * description and a title that lists several things both stretch it - and a
 * clamp to [10, 180] rounded to 5. Three hours is the cap on purpose: a longer
 * task is really several, and the board should show the first sitting.
 */
export function estimateMinutes(task: {
  title: string;
  description?: string | null;
  context?: string | null;
}): Estimate {
  const title = task.title.trim();
  const description = (task.description ?? "").trim();

  const stated = statedMinutes(`${title}\n${description.slice(0, 400)}`);
  if (stated != null) {
    return { minutes: roundTo5(stated), basis: "stated", label: "stated in the task" };
  }

  let minutes = DEFAULT_MINUTES;
  let basis: EstimateBasis = "default";
  let label = "no strong signal";

  const lower = title.toLowerCase();
  let bestPos = Infinity;
  for (const tier of TIERS) {
    const pos = earliestMatch(lower, tier);
    if (pos < bestPos) {
      bestPos = pos;
      minutes = tier.minutes;
      basis = "keyword";
      label = tier.label;
    }
  }

  if (basis === "default" && task.context && TIER_BY_CONTEXT[task.context]) {
    const c = TIER_BY_CONTEXT[task.context];
    minutes = c.minutes;
    basis = "context";
    label = c.label;
  }

  // Modifiers. A long description means the task carries its own sub-steps;
  // a title that enumerates ("A, B, and C") is several things in one row.
  let factor = 1;
  if (description.length > 400) factor *= 1.25;
  const enumerated = (title.match(/,|\band\b|&|\+|\/|그리고/g) ?? []).length;
  if (enumerated >= 2) factor *= 1.25;
  else if (enumerated === 1 && minutes <= 30) factor *= 1.25;
  if (description.length > 400 || enumerated >= 1) label += factor > 1 ? ", stretched for scope" : "";

  return { minutes: roundTo5(minutes * factor), basis, label };
}

// ---------- the plan ----------

export interface PlannableTask {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  priority: string;
  context: string | null;
  isHighlight: boolean;
  dueDate: Date | null;
  scheduledDate: Date | null;
  createdAt: Date;
  /** From getTodayTasks: a date that fell before today. */
  overdue?: boolean;
}

export type PlanItem =
  | {
      kind: "block";
      id: string;
      blockKind: BlockKind;
      mode?: WorkMode;
      label: string;
      hint?: string;
      start: string;
      end: string;
    }
  | {
      kind: "task";
      taskId: string;
      title: string;
      start: string;
      end: string;
      minutes: number;
      estimate: Estimate;
      /** Placed at a time the task itself carries (a 2pm meeting). */
      pinned: boolean;
      why: string;
    }
  | { kind: "break"; start: string; end: string; label: string }
  | { kind: "reminder"; id: string; label: string; start: string; end: string }
  | { kind: "open"; start: string; end: string };

export type UnplacedReason = "day_full" | "no_room" | "waiting";

export interface UnplacedTask {
  taskId: string;
  title: string;
  minutes: number;
  reason: UnplacedReason;
}

export interface DayPlan {
  version: 1;
  /** yyyy-MM-dd of the day it plans. */
  date: string;
  generatedAt: string;
  /** Planning starts here: the later of wake and the moment it was generated. */
  from: string;
  items: PlanItem[];
  unplaced: UnplacedTask[];
  plannedMinutes: number;
  openMinutes: number;
  breakMinutes: number;
}

const OPEN_MIN = 15;

function atClock(day: Date, hhmm: string): Date {
  const [h, m] = hhmm.split(":").map((x) => parseInt(x, 10));
  const d = new Date(day);
  d.setHours(h, m, 0, 0);
  return d;
}

function addMin(d: Date, minutes: number): Date {
  return new Date(d.getTime() + minutes * 60_000);
}

function diffMin(a: Date, b: Date): number {
  return Math.round((b.getTime() - a.getTime()) / 60_000);
}

function ceilTo5(d: Date): Date {
  const ms = 5 * 60_000;
  return new Date(Math.ceil(d.getTime() / ms) * ms);
}

function priorityRank(p: string): number {
  return PRIORITY_META[p as Priority]?.rank ?? PRIORITY_META.medium.rank;
}

interface Window {
  start: Date;
  end: Date;
  mode: WorkMode;
}

/** Carve pinned intervals out of a window; keeps only positive remainders. */
function subtract(windows: Window[], busy: { start: Date; end: Date }[]): Window[] {
  let out = windows;
  for (const b of busy) {
    out = out.flatMap((w) => {
      if (b.end <= w.start || b.start >= w.end) return [w];
      const parts: Window[] = [];
      if (b.start > w.start) parts.push({ ...w, end: b.start });
      if (b.end < w.end) parts.push({ ...w, start: b.end });
      return parts;
    });
  }
  return out.filter((w) => diffMin(w.start, w.end) >= 5);
}

/**
 * Pack today's open tasks into the work blocks between `now` and the end of
 * the last work block.
 *
 * - Tasks carrying a time today (a 2pm meeting) are pinned at that time and
 *   carve the windows; a pinned time already past falls back to flexible.
 * - Flexible tasks go highlight first, then overdue, then by priority, then
 *   due-today before scheduled-only, then longer before shorter, then oldest
 *   first. Each window takes the
 *   first task in that order that fits it; a "light" window (after dinner)
 *   only takes short ones.
 * - Sustainability rules from the template: at most `maxPlannedTaskHours` of
 *   tasks in a day, so open time survives as buffer; a break after
 *   `focusBreakAfterMinutes` of back-to-back work. Remaining tasks are listed
 *   as not fitting, with the reason, rather than crammed in.
 */
export function buildDayPlan(template: DayTemplate, tasks: PlannableTask[], now: Date): DayPlan {
  const day = startOfDay(now);
  const dayEnd = endOfDay(now);
  const from = ceilTo5(new Date(Math.max(now.getTime(), atClock(day, template.wake).getTime())));
  const { planning } = template;

  const blocks = template.blocks.map((b) => ({
    ...b,
    startAt: atClock(day, b.start),
    endAt: atClock(day, b.end),
  }));

  // Work windows still ahead of `from`.
  let windows: Window[] = blocks
    .filter((b) => b.kind === "work" && b.endAt > from)
    .map((b) => ({ start: b.startAt > from ? b.startAt : from, end: b.endAt, mode: b.mode ?? "focus" }));

  const items: PlanItem[] = [];
  const unplaced: UnplacedTask[] = [];

  // Template blocks still ahead (the whole day when planned at 06:00).
  for (const b of blocks) {
    if (b.endAt <= from) continue;
    items.push({
      kind: "block",
      id: b.id,
      blockKind: b.kind,
      ...(b.kind === "work" ? { mode: b.mode ?? "focus" } : {}),
      label: b.label,
      ...(b.hint ? { hint: b.hint } : {}),
      start: (b.startAt > from ? b.startAt : from).toISOString(),
      end: b.endAt.toISOString(),
    });
  }

  // Reminders ride on their block: shown whenever the block is, clipped to
  // `from` so the morning one still appears on a board built at 06:15.
  for (const rm of template.reminders) {
    const b = blocks.find((x) => x.id === rm.block);
    if (!b || b.endAt <= from) continue;
    const at = rm.when === "start" ? b.startAt : b.endAt;
    const shown = at > from ? at : from;
    if (rm.when === "end" && b.endAt <= from) continue;
    items.push({
      kind: "reminder",
      id: rm.id,
      label: rm.label,
      start: shown.toISOString(),
      end: shown.toISOString(),
    });
  }

  // Candidates: open tasks they can act on. "waiting" is on someone else.
  const estimates = new Map<string, Estimate>();
  const candidates: PlannableTask[] = [];
  for (const t of tasks) {
    if (t.status === "completed" || t.status === "canceled") continue;
    if (t.status === "waiting") {
      unplaced.push({ taskId: t.id, title: t.title, minutes: 0, reason: "waiting" });
      continue;
    }
    estimates.set(t.id, estimateMinutes(t));
    candidates.push(t);
  }

  // Pinned: a time of day on today's date, still ahead.
  const pinnedTimes = new Map<string, Date>();
  for (const t of candidates) {
    const stamp = [t.scheduledDate, t.dueDate].find(
      (d) => d && d >= day && d <= dayEnd && hasTimeOfDay(d),
    );
    if (stamp && stamp >= from) pinnedTimes.set(t.id, stamp);
  }
  let plannedMinutes = 0;
  const busy: { start: Date; end: Date }[] = [];
  for (const t of candidates) {
    const at = pinnedTimes.get(t.id);
    if (!at) continue;
    const est = estimates.get(t.id)!;
    const end = addMin(at, est.minutes);
    items.push({
      kind: "task",
      taskId: t.id,
      title: t.title,
      start: at.toISOString(),
      end: end.toISOString(),
      minutes: est.minutes,
      estimate: est,
      pinned: true,
      why: `at ${format(at, "h:mm a")}`,
    });
    busy.push({ start: at, end });
    plannedMinutes += est.minutes;
  }
  windows = subtract(windows, busy);

  const flexible = candidates
    .filter((t) => !pinnedTimes.has(t.id))
    .sort((a, b) => {
      if (a.isHighlight !== b.isHighlight) return a.isHighlight ? -1 : 1;
      if (!!a.overdue !== !!b.overdue) return a.overdue ? -1 : 1;
      const pr = priorityRank(a.priority) - priorityRank(b.priority);
      if (pr) return pr;
      const ad = a.dueDate && a.dueDate <= dayEnd ? 0 : 1;
      const bd = b.dueDate && b.dueDate <= dayEnd ? 0 : 1;
      if (ad !== bd) return ad - bd;
      const dd = (a.dueDate?.getTime() ?? Infinity) - (b.dueDate?.getTime() ?? Infinity);
      if (dd) return dd;
      // Same tier: longer first. Deep work should claim the focus blocks
      // while attention is fresh; quick tasks fit the gaps around it, and a
      // two-hour bench task must not be crowded out by five errands captured
      // earlier.
      const ml = estimates.get(b.id)!.minutes - estimates.get(a.id)!.minutes;
      if (ml) return ml;
      return a.createdAt.getTime() - b.createdAt.getTime();
    });

  let budget = planning.maxPlannedTaskHours * 60 - plannedMinutes;
  const placed = new Set<string>();
  let openMinutes = 0;
  let breakMinutes = 0;

  const whyFor = (t: PlannableTask, mode: WorkMode): string => {
    if (t.isHighlight) return "today's highlight";
    if (t.overdue) return "overdue";
    if (t.priority === "urgent" || t.priority === "high") return `${t.priority} priority`;
    if (t.dueDate && t.dueDate <= dayEnd) return "due today";
    return mode === "light" ? "short enough for the evening" : "scheduled today";
  };

  for (const w of windows.sort((a, b) => a.start.getTime() - b.start.getTime())) {
    let cursor = w.start;
    let sinceBreak = 0;
    // A window that starts right after a pinned task or a previous window is
    // still continuous work; approximate with the window boundary, which is a
    // break (meal) in every template case that matters.
    while (diffMin(cursor, w.end) >= MIN_TASK_MINUTES) {
      const remaining = diffMin(cursor, w.end);
      const next = flexible.find((t) => {
        if (placed.has(t.id)) return false;
        const m = estimates.get(t.id)!.minutes;
        if (m > remaining || m > budget) return false;
        if (w.mode === "light" && m > planning.lightMaxTaskMinutes) return false;
        return true;
      });
      if (!next) break;
      const m = estimates.get(next.id)!.minutes;
      if (
        sinceBreak >= planning.focusBreakAfterMinutes &&
        remaining >= m + planning.breakMinutes
      ) {
        const bEnd = addMin(cursor, planning.breakMinutes);
        items.push({
          kind: "break",
          start: cursor.toISOString(),
          end: bEnd.toISOString(),
          label: "Break: stand up, water, eyes off the screen",
        });
        breakMinutes += planning.breakMinutes;
        cursor = bEnd;
        sinceBreak = 0;
      }
      const end = addMin(cursor, m);
      items.push({
        kind: "task",
        taskId: next.id,
        title: next.title,
        start: cursor.toISOString(),
        end: end.toISOString(),
        minutes: m,
        estimate: estimates.get(next.id)!,
        pinned: false,
        why: whyFor(next, w.mode),
      });
      placed.add(next.id);
      plannedMinutes += m;
      budget -= m;
      sinceBreak += m;
      cursor = end;
    }
    const left = diffMin(cursor, w.end);
    if (left >= OPEN_MIN) {
      items.push({ kind: "open", start: cursor.toISOString(), end: w.end.toISOString() });
      openMinutes += left;
    } else if (left > 0) {
      openMinutes += left;
    }
  }

  for (const t of flexible) {
    if (placed.has(t.id)) continue;
    const m = estimates.get(t.id)!.minutes;
    unplaced.push({
      taskId: t.id,
      title: t.title,
      minutes: m,
      reason: m > budget ? "day_full" : "no_room",
    });
  }

  // At one instant: the reminder first ("after lunch" reads before the
  // afternoon header), then the block header, then what fills it.
  const order: Record<PlanItem["kind"], number> = { reminder: 0, block: 1, break: 2, task: 2, open: 3 };
  items.sort((a, b) => a.start.localeCompare(b.start) || order[a.kind] - order[b.kind]);

  return {
    version: 1,
    date: format(day, "yyyy-MM-dd"),
    generatedAt: now.toISOString(),
    from: from.toISOString(),
    items,
    unplaced,
    plannedMinutes,
    openMinutes,
    breakMinutes,
  };
}

// ---------- storage + reconciliation ----------

async function readStoredPlan(): Promise<DayPlan | null> {
  try {
    const raw = JSON.parse(await fs.readFile(PLAN_FILE, "utf8")) as Partial<DayPlan>;
    if (raw.version !== 1 || typeof raw.date !== "string" || !Array.isArray(raw.items)) return null;
    return raw as DayPlan;
  } catch {
    return null;
  }
}

async function writePlan(plan: DayPlan): Promise<void> {
  await fs.mkdir(path.dirname(PLAN_FILE), { recursive: true });
  const temp = `${PLAN_FILE}.${process.pid}.tmp`;
  await fs.writeFile(temp, JSON.stringify(plan, null, 2), "utf8");
  await fs.rename(temp, PLAN_FILE);
}

/**
 * Build today's plan from the live task table and store it. The "Regenerate"
 * button and the first view of a new day both land here.
 */
export async function regenerateDayPlan(now = new Date()): Promise<DayPlan> {
  const [template, tasks] = await Promise.all([loadDayTemplate(), getTodayTasks(now)]);
  const plan = buildDayPlan(template, tasks, now);
  await writePlan(plan);
  return plan;
}

/**
 * Put a task on the plan at a time they chose - a drop from the "doesn't fit" /
 * "added since" lists onto the Plan column (2026-09-17).
 *
 * The mechanism is the one the planner already has: a task carrying a time
 * today is pinned and carves the windows. So the task's action date becomes
 * that time (the same write the week strip's drag makes), and the stored plan
 * is rebuilt around it. Rebuilt AS OF THE PLAN'S OWN START, not now: a rebuild
 * as of 15:00 would drop the morning off the board, and their placing one task
 * is not a request to forget the rest of the day. Only when there is no plan
 * for today does this fall back to a fresh one. Their pins survive Regenerate
 * too, because they live on the task, not in the plan file.
 */
export async function placeTaskInPlan(taskId: string, startAt: Date, now = new Date()): Promise<DayPlan> {
  await rescheduleTask(taskId, startAt);
  const today = format(startOfDay(now), "yyyy-MM-dd");
  const [template, tasks, stored] = await Promise.all([loadDayTemplate(), getTodayTasks(now), readStoredPlan()]);
  const keep = stored && stored.date === today ? stored : null;
  // The pin must not fall before the plan's start, or it would read as flexible.
  const asOf = keep ? new Date(Math.min(new Date(keep.from).getTime(), startAt.getTime())) : now;
  const plan = buildDayPlan(template, tasks, asOf);
  if (keep) plan.generatedAt = keep.generatedAt;
  await writePlan(plan);
  return plan;
}

export type BoardTaskState = "open" | "done" | "removed";

export interface BoardTask {
  id: string;
  title: string;
  status: string;
  priority: string;
  context: string | null;
  isHighlight: boolean;
  dueDate: Date | null;
  scheduledDate: Date | null;
  project: { id: string; title: string } | null;
  area: { id: string; title: string } | null;
  state: BoardTaskState;
}

export interface DayPlanBoard {
  plan: DayPlan;
  template: DayTemplate;
  /** Live state for every task the plan names, keyed by id. */
  tasks: Record<string, BoardTask>;
  /** Open tasks for today that the stored plan has never seen. */
  newSince: BoardTask[];
  /** What they actually did today, for the right-hand column. */
  entries: TimeEntry[];
}

/**
 * The stored plan for today, regenerated if there is none (or it is
 * yesterday's), overlaid with the live task table: completions, removals,
 * and tasks added since the plan was made. Never rewrites the stored plan on
 * a read - that is what the Regenerate button is for.
 */
export async function getDayPlanBoard(now = new Date()): Promise<DayPlanBoard> {
  const today = format(startOfDay(now), "yyyy-MM-dd");
  const template = await loadDayTemplate();
  let plan = await readStoredPlan();
  if (!plan || plan.date !== today) plan = await regenerateDayPlan(now);

  const named = new Set<string>();
  for (const it of plan.items) if (it.kind === "task") named.add(it.taskId);
  for (const u of plan.unplaced) named.add(u.taskId);

  const [live, todays, entries] = await Promise.all([
    named.size
      ? db.task.findMany({
          where: { id: { in: [...named] } },
          include: {
            project: { select: { id: true, title: true } },
            area: { select: { id: true, title: true } },
          },
        })
      : Promise.resolve([]),
    getTodayTasks(now),
    listTimeEntries(now),
  ]);

  const toBoard = (t: (typeof live)[number], state: BoardTaskState): BoardTask => ({
    id: t.id,
    title: t.title,
    status: t.status,
    priority: t.priority,
    context: t.context,
    isHighlight: t.isHighlight,
    dueDate: t.dueDate,
    scheduledDate: t.scheduledDate,
    project: t.project,
    area: t.area,
    state,
  });

  const tasks: Record<string, BoardTask> = {};
  for (const t of live) {
    const state: BoardTaskState =
      t.status === "completed" ? "done" : t.archivedAt || t.status === "canceled" ? "removed" : "open";
    tasks[t.id] = toBoard(t, state);
  }
  for (const id of named) {
    if (!tasks[id]) {
      const snapshot =
        plan.items.find((it) => it.kind === "task" && it.taskId === id) ??
        plan.unplaced.find((u) => u.taskId === id);
      const title = snapshot && "title" in snapshot ? snapshot.title : "(removed)";
      tasks[id] = {
        id,
        title,
        status: "canceled",
        priority: "medium",
        context: null,
        isHighlight: false,
        dueDate: null,
        scheduledDate: null,
        project: null,
        area: null,
        state: "removed",
      };
    }
  }

  const newSince = todays
    .filter((t) => !named.has(t.id) && t.status !== "waiting")
    .map((t) => toBoard(t, "open"));

  return { plan, template, tasks, newSince, entries };
}
