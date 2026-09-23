import { endOfDay, startOfDay, addDays, startOfWeek, endOfWeek } from "date-fns";
import { db } from "@/lib/db";
import { hasTimeOfDay } from "@/lib/utils";
import { OPEN_TASK_STATUSES, PRIORITY_META, type Priority } from "@/lib/types";
import type { z } from "zod";
import type { taskInputSchema } from "@/lib/validators";

function priorityRank(p: string): number {
  return PRIORITY_META[p as Priority]?.rank ?? PRIORITY_META.medium.rank;
}

type TaskInput = z.infer<typeof taskInputSchema>;

const taskInclude = {
  project: { select: { id: true, title: true } },
  area: { select: { id: true, title: true } },
  tags: true,
} as const;

async function areaForProject(
  projectId: string | null | undefined,
  fallback: string | null | undefined,
) {
  if (!projectId) return fallback;
  const project = await db.project.findUnique({
    where: { id: projectId },
    select: { areaId: true },
  });
  return project?.areaId ?? fallback;
}

export async function createTask(input: TaskInput) {
  const { tags, ...data } = input;
  const areaId = await areaForProject(data.projectId, data.areaId);
  return db.task.create({
    data: {
      ...data,
      areaId,
      tags: tags?.length
        ? { connectOrCreate: tags.map((name) => ({ where: { name }, create: { name } })) }
        : undefined,
    },
  });
}

export async function updateTask(id: string, input: Partial<TaskInput>) {
  const { tags, ...data } = input;
  const current = await db.task.findUniqueOrThrow({
    where: { id },
    select: {
      projectId: true,
      areaId: true,
      status: true,
      previousStatus: true,
    },
  });
  const projectId =
    data.projectId !== undefined ? data.projectId : current.projectId;
  const requestedArea =
    data.areaId !== undefined ? data.areaId : current.areaId;
  const areaId = await areaForProject(projectId, requestedArea);

  /**
   * Completion bookkeeping, matching toggleTaskComplete().
   *
   * Without this, setting status to "completed" through the edit dialog left
   * `completedAt` null — so the task looked done everywhere that reads
   * `status`, and was invisible everywhere that reads `completedAt`
   * (`/reviews`, "Done today"). Only computed when `status` is actually part of
   * the patch, so unrelated edits never disturb a completion timestamp.
   */
  let completion: {
    completedAt?: Date | null;
    previousStatus?: string | null;
    isHighlight?: boolean;
  } = {};
  if (data.status !== undefined && data.status !== current.status) {
    const completing = data.status === "completed";
    const wasCompleted = current.status === "completed";
    if (completing) {
      // A finished task is not today's one thing.
      completion = {
        completedAt: new Date(),
        previousStatus: current.status,
        isHighlight: false,
      };
    } else if (wasCompleted) {
      completion = { completedAt: null, previousStatus: null };
    }
  }

  return db.$transaction(async (tx) => {
    // The single-highlight invariant lives in setTaskHighlight(); an edit that
    // sets isHighlight has to honour it too, or two tasks end up starred and
    // /today shows whichever one it happens to find first.
    if (data.isHighlight === true) {
      await tx.task.updateMany({
        where: { isHighlight: true, id: { not: id } },
        data: { isHighlight: false },
      });
    }
    return tx.task.update({
      where: { id },
      data: {
        ...data,
        ...completion,
        areaId,
        tags: tags
          ? {
              set: [],
              connectOrCreate: tags.map((name) => ({ where: { name }, create: { name } })),
            }
          : undefined,
      },
    });
  });
}

/**
 * Move a task to another calendar day without changing what kind of date it
 * carries. Due-dated tasks keep using dueDate; scheduled-only tasks keep using
 * scheduledDate. Preserve the source time so dragging a 2:30pm task changes
 * its day, not its meaning.
 */
export async function moveTaskToCalendarDate(id: string, targetDate: Date) {
  const current = await db.task.findUniqueOrThrow({
    where: { id },
    select: { dueDate: true, scheduledDate: true },
  });
  const field = current.dueDate ? "dueDate" : "scheduledDate";
  const source = current[field];
  if (!source) throw new Error("Task has no calendar date to move");

  const moved = new Date(targetDate);
  moved.setHours(
    source.getHours(),
    source.getMinutes(),
    source.getSeconds(),
    source.getMilliseconds(),
  );

  return db.task.update({
    where: { id },
    data: field === "dueDate" ? { dueDate: moved } : { scheduledDate: moved },
  });
}

export async function toggleTaskComplete(id: string) {
  const task = await db.task.findUniqueOrThrow({ where: { id } });
  const completing = task.status !== "completed";
  return db.task.update({
    where: { id },
    data: {
      status: completing ? "completed" : task.previousStatus || "next",
      previousStatus: completing ? task.status : null,
      completedAt: completing ? new Date() : null,
    },
  });
}

export async function setTaskHighlight(id: string, isHighlight: boolean) {
  return db.$transaction(async (tx) => {
    if (isHighlight) {
      await tx.task.updateMany({
        where: { isHighlight: true, id: { not: id } },
        data: { isHighlight: false },
      });
    }
    return tx.task.update({ where: { id }, data: { isHighlight } });
  });
}

export async function rescheduleTask(id: string, scheduledDate: Date | null) {
  const task = await db.task.findUniqueOrThrow({ where: { id } });
  return db.task.update({
    where: { id },
    data: {
      scheduledDate,
      status: scheduledDate ? "scheduled" : task.previousStatus || "next",
      previousStatus: scheduledDate
        ? task.status === "scheduled"
          ? task.previousStatus
          : task.status
        : null,
    },
  });
}

export async function deleteTask(id: string) {
  return db.$transaction(async (tx) => {
    await tx.project.updateMany({
      where: { nextActionId: id },
      data: { nextActionId: null },
    });
    return tx.task.update({
      where: { id },
      data: {
        archivedAt: new Date(),
        status: "canceled",
        isHighlight: false,
      },
    });
  });
}

/** Tasks due or scheduled today, plus overdue open tasks. */
/**
 * Sweep every completed task off the active lists in one go.
 *
 * Soft, like the single-task delete above: `archivedAt` is stamped and the row
 * stays queryable from /archive. A hard delete would take the completion
 * history with it, and this is the one button in the app that can touch
 * hundreds of rows at once — the wrong place to make deletion irreversible.
 * Returns the count so the caller can report what it swept.
 */
export async function clearCompletedTasks() {
  const { count } = await db.task.updateMany({
    where: { status: "completed", archivedAt: null },
    data: { archivedAt: new Date(), isHighlight: false },
  });
  return count;
}

/**
 * Open tasks carrying a date that has already passed.
 *
 * "Overdue" here is the /today card's own definition — a date strictly before
 * the start of today — rather than utils.isOverdue(), which also flags a task
 * timed for 9am when it is now 3pm. Pulling something from earlier today *into*
 * today is a no-op, so it has no business inflating the button's count.
 *
 * Two ways in, because the card shows two kinds of red line:
 *   - a passed action date, which needs moving onto today;
 *   - a passed due date on work that is already today's or unplanned, which
 *     needs only the stale deadline reset.
 * The second clause was missing until 2026-08-19, so four tasks scheduled for
 * today still reading "Overdue due Aug 16" left the button hidden at count 0 —
 * the number disagreed with what was on screen.
 *
 * A task carrying a *future* action date is still excluded even when its due
 * date has passed: it has a plan, and a sweep should not overwrite one they made
 * deliberately.
 *
 * One definition, two callers (count and move), so the number on the button
 * cannot drift from the set the press touches.
 */
function pullableOverdueWhere(dayStart: Date, dayEnd: Date) {
  return {
    status: { in: OPEN_TASK_STATUSES },
    archivedAt: null,
    OR: [
      { scheduledDate: { lt: dayStart } },
      {
        AND: [
          { dueDate: { lt: dayStart } },
          { OR: [{ scheduledDate: null }, { scheduledDate: { lte: dayEnd } }] },
        ],
      },
    ],
  };
}

export async function countPullableOverdueTasks(now = new Date()) {
  return db.task.count({
    where: pullableOverdueWhere(startOfDay(now), endOfDay(now)),
  });
}

/** Same day, same clock time; all-day dates stay all-day (midnight). */
function moveDateToDay(source: Date | null, dayStart: Date) {
  const moved = new Date(dayStart);
  if (source && hasTimeOfDay(source)) {
    moved.setHours(
      source.getHours(),
      source.getMinutes(),
      source.getSeconds(),
      source.getMilliseconds(),
    );
  }
  return moved;
}

/**
 * Pull every overdue task onto today's list in one press.
 *
 * It writes `scheduledDate` — the action date, "when I will work on this" —
 * and it also resets a *missed* due date to today (the owner, 2026-08-19: the
 * sweep means "these are today's tasks now", and a wall of red "Overdue due
 * Aug 12" lines after pressing it read as the button not having worked). A
 * due date that has not passed yet is left alone — it is still a real future
 * deadline. For a task already scheduled for today, clearing the stale
 * deadline is the whole effect; its action date is rewritten to the value it
 * already had.
 *
 * Status is left alone. rescheduleTask() rewrites it to "scheduled", which
 * is right for one deliberate reschedule and wrong for a sweep — it would
 * demote every in-progress task it touched. getTodayTasks() keys off dates, not
 * status, so the move is enough.
 *
 * Time of day is preserved on both dates, matching moveTaskToCalendarDate():
 * a 2:30pm task changes its day, not its meaning. All-day tasks stay all-day
 * (midnight), which is what hasTimeOfDay() reads them as.
 */
export async function pullOverdueTasksToToday(now = new Date()) {
  const dayStart = startOfDay(now);
  const overdue = await db.task.findMany({
    where: pullableOverdueWhere(dayStart, endOfDay(now)),
    select: { id: true, dueDate: true, scheduledDate: true },
  });
  if (!overdue.length) return 0;

  await db.$transaction(
    overdue.map((task) => {
      const dueMissed = task.dueDate != null && task.dueDate < dayStart;
      return db.task.update({
        where: { id: task.id },
        data: {
          scheduledDate: moveDateToDay(task.scheduledDate ?? task.dueDate, dayStart),
          ...(dueMissed ? { dueDate: moveDateToDay(task.dueDate, dayStart) } : {}),
        },
      });
    }),
  );

  return overdue.length;
}

export async function getTodayTasks(now = new Date()) {
  const dayStart = startOfDay(now);
  const dayEnd = endOfDay(now);
  return db.task.findMany({
    where: {
      status: { in: OPEN_TASK_STATUSES },
      archivedAt: null,
      OR: [
        { dueDate: { lte: dayEnd } },
        { scheduledDate: { lte: dayEnd } },
        { isHighlight: true },
      ],
    },
    orderBy: [{ isHighlight: "desc" }, { dueDate: "asc" }, { scheduledDate: "asc" }],
    include: taskInclude,
  }).then((tasks) =>
    tasks.filter(
      (t) =>
        t.isHighlight ||
        (t.dueDate && t.dueDate <= dayEnd) ||
        (t.scheduledDate && t.scheduledDate <= dayEnd) ||
        false
    )
    // Highlight first, then priority (urgent → low). priority is a plain
    // string column, so the rank comes from PRIORITY_META rather than SQL;
    // the sort is stable, so the date order above breaks ties.
    .sort(
      (a, b) =>
        Number(b.isHighlight) - Number(a.isHighlight) ||
        priorityRank(a.priority) - priorityRank(b.priority)
    )
    .map((t) => ({
      ...t,
      overdue:
        (t.dueDate != null && t.dueDate < dayStart) ||
        (t.scheduledDate != null && t.scheduledDate < dayStart),
    }))
  );
}

export async function getUpcomingTasks(days = 14, now = new Date()) {
  const from = endOfDay(now);
  const to = endOfDay(addDays(now, days));
  return db.task.findMany({
    where: {
      status: { in: OPEN_TASK_STATUSES },
      archivedAt: null,
      OR: [
        { dueDate: { gt: from, lte: to } },
        { scheduledDate: { gt: from, lte: to } },
      ],
    },
    orderBy: [{ dueDate: "asc" }, { scheduledDate: "asc" }],
    include: taskInclude,
  });
}

export type TaskFilters = {
  status?: string;
  priority?: string;
  context?: string;
  projectId?: string;
  areaId?: string;
  view?: "inbox" | "triage" | "today" | "upcoming" | "completed" | "all" | "waiting" | "someday";
};

/**
 * A task "needs triage" when it is active but has neither a due date nor an
 * action date (`scheduledDate`). Waiting and Someday are intentionally exempt:
 * they represent deferred state rather than a calendar commitment. Kept in
 * sync with missingDetail() in src/lib/utils.ts.
 */
const TRIAGE_AND = [
  { status: { notIn: ["waiting", "someday", "completed", "canceled"] } },
  { dueDate: null },
  { scheduledDate: null },
];

export async function listTasks(filters: TaskFilters = {}) {
  const now = new Date();
  const where: NonNullable<Parameters<typeof db.task.findMany>[0]>["where"] = {
    archivedAt: null,
  };

  switch (filters.view) {
    case "inbox":
      // Backward-compatible alias for old bookmarks. The standalone Inbox tab
      // was redundant and did not identify work that actually needed a decision.
      where.AND = TRIAGE_AND;
      break;
    case "triage":
      where.AND = TRIAGE_AND;
      break;
    case "today":
      where.status = { in: OPEN_TASK_STATUSES };
      where.OR = [
        { dueDate: { lte: endOfDay(now) } },
        { scheduledDate: { lte: endOfDay(now) } },
        { isHighlight: true },
      ];
      break;
    case "upcoming":
      where.status = { in: OPEN_TASK_STATUSES };
      where.OR = [
        { dueDate: { gt: endOfDay(now) } },
        { scheduledDate: { gt: endOfDay(now) } },
      ];
      break;
    case "completed":
      where.status = "completed";
      break;
    case "waiting":
      where.status = "waiting";
      break;
    case "someday":
      where.status = "someday";
      break;
    default:
      if (filters.status) where.status = filters.status;
      else where.status = { in: OPEN_TASK_STATUSES };
  }

  if (filters.priority) where.priority = filters.priority;
  if (filters.context) where.context = filters.context;
  if (filters.projectId) where.projectId = filters.projectId;
  if (filters.areaId) where.areaId = filters.areaId;

  return db.task.findMany({
    where,
    orderBy:
      filters.view === "completed"
        ? [{ completedAt: "desc" }]
        : [{ isHighlight: "desc" }, { dueDate: "asc" }, { scheduledDate: "asc" }, { createdAt: "desc" }],
    include: taskInclude,
    take: 200,
  });
}

/** All tasks (open or done) dated within the current Mon–Sun week. */
export async function getWeekTasks(now = new Date()) {
  const from = startOfWeek(now, { weekStartsOn: 1 });
  const to = endOfWeek(now, { weekStartsOn: 1 });
  return db.task.findMany({
    where: {
      archivedAt: null,
      status: { not: "canceled" },
      OR: [
        { dueDate: { gte: from, lte: to } },
        { scheduledDate: { gte: from, lte: to } },
      ],
    },
    orderBy: [{ status: "asc" }, { priority: "asc" }, { createdAt: "asc" }],
    include: taskInclude,
  });
}

/** How many open tasks need triage — for the tab badge and Home stat. */
export async function countTriageTasks() {
  return db.task.count({ where: { archivedAt: null, AND: TRIAGE_AND } });
}

export async function getCompletedInRange(from: Date, to: Date) {
  return db.task.findMany({
    where: { status: "completed", completedAt: { gte: from, lte: to } },
    orderBy: { completedAt: "desc" },
    include: taskInclude,
  });
}
