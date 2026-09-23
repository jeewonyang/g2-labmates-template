import { endOfDay, startOfDay } from "date-fns";
import type { z } from "zod";
import { db } from "@/lib/db";
import type { timeEntryInputSchema } from "@/lib/validators";

/**
 * The Actual side of the Plan & actual board (2026-09-17).
 *
 * A TimeEntry is a stretch of the day they say she spent on something: a task
 * from the plan, a fixed block they kept (lunch, the workout), or anything else.
 * The plan is regenerated and lives in a state file; this is the durable record
 * of what actually happened, so it lives in Prisma with everything else she
 * writes down, and deleting one archives it like every other entity here.
 *
 * Nothing in this file infers. Logging time against a task does not complete
 * the task, and a task completed elsewhere does not create an entry - the two
 * are different claims ("I worked on it" vs "it is done") and the board shows
 * both without merging them.
 */

export type TimeEntryInput = z.infer<typeof timeEntryInputSchema>;

export interface TimeEntry {
  id: string;
  startAt: Date;
  endAt: Date;
  title: string;
  kind: string;
  taskId: string | null;
  blockId: string | null;
  note: string | null;
}

const select = {
  id: true,
  startAt: true,
  endAt: true,
  title: true,
  kind: true,
  taskId: true,
  blockId: true,
  note: true,
} as const;

/** Every unarchived entry on the calendar day containing `day`, in time order. */
export async function listTimeEntries(day = new Date()): Promise<TimeEntry[]> {
  return db.timeEntry.findMany({
    where: { day: { gte: startOfDay(day), lte: endOfDay(day) }, archivedAt: null },
    orderBy: { startAt: "asc" },
    select,
  });
}

export async function createTimeEntry(input: TimeEntryInput): Promise<TimeEntry> {
  return db.timeEntry.create({
    data: {
      day: startOfDay(input.startAt),
      startAt: input.startAt,
      endAt: input.endAt,
      title: input.title,
      kind: input.kind,
      taskId: input.taskId ?? null,
      blockId: input.blockId ?? null,
      note: input.note ?? null,
    },
    select,
  });
}

export async function updateTimeEntry(id: string, input: TimeEntryInput): Promise<TimeEntry> {
  return db.timeEntry.update({
    where: { id },
    data: {
      day: startOfDay(input.startAt),
      startAt: input.startAt,
      endAt: input.endAt,
      title: input.title,
      kind: input.kind,
      taskId: input.taskId ?? null,
      blockId: input.blockId ?? null,
      note: input.note ?? null,
    },
    select,
  });
}

/** Soft: the row stays, hidden. There is no hard delete on this table. */
export async function archiveTimeEntry(id: string): Promise<void> {
  await db.timeEntry.update({ where: { id }, data: { archivedAt: new Date() } });
}
