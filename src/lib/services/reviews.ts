import {
  endOfMonth,
  endOfQuarter,
  endOfWeek,
  startOfDay,
  startOfMonth,
  startOfQuarter,
  startOfWeek,
  endOfDay,
} from "date-fns";
import { db } from "@/lib/db";
import { getCompletedInRange } from "@/lib/services/tasks";
import { getActiveProjects, getCompletedProjectsInRange } from "@/lib/services/projects";
import type { ReviewType } from "@/lib/types";
import type { z } from "zod";
import type { reviewInputSchema } from "@/lib/validators";

type ReviewInput = z.infer<typeof reviewInputSchema>;

/** The period a review of the given type covers, anchored at `date`. */
export function reviewPeriod(type: ReviewType, date: Date) {
  switch (type) {
    case "daily":
      return { from: startOfDay(date), to: endOfDay(date) };
    case "weekly":
      return {
        from: startOfWeek(date, { weekStartsOn: 1 }),
        to: endOfWeek(date, { weekStartsOn: 1 }),
      };
    case "monthly":
      return { from: startOfMonth(date), to: endOfMonth(date) };
    case "quarterly":
      return { from: startOfQuarter(date), to: endOfQuarter(date) };
  }
}

export async function listReviews(type?: string) {
  return db.review.findMany({
    where: { archivedAt: null, ...(type ? { type } : {}) },
    orderBy: { date: "desc" },
    take: 100,
  });
}

export async function getReview(id: string) {
  return db.review.findUnique({ where: { id } });
}

export async function upsertReview(input: ReviewInput) {
  const date = startOfDay(input.date);
  return db.review.upsert({
    where: { type_date: { type: input.type, date } },
    create: { ...input, date, contentMarkdown: input.contentMarkdown ?? "" },
    update: { ...input, date, archivedAt: null },
  });
}

export async function deleteReview(id: string) {
  return db.review.update({ where: { id }, data: { archivedAt: new Date() } });
}

/**
 * Whether the week containing `now` already has a weekly review.
 *
 * `/today` uses this to prompt for one. Without a prompt the review is a page
 * you have to remember to visit, which is why exactly one has ever been
 * written — and now that priorities become tasks, skipping it costs real work.
 */
export async function getWeeklyReviewStatus(now = new Date()) {
  const { from, to } = reviewPeriod("weekly", now);
  const review = await db.review.findFirst({
    where: { type: "weekly", date: { gte: from, lte: to }, archivedAt: null },
    orderBy: { date: "desc" },
  });
  return { done: Boolean(review), weekStart: from, weekEnd: to, review };
}

/**
 * Everything a review page needs to reflect on a period:
 * completed tasks/projects in range plus the current active-project list.
 */
export async function getReviewContext(type: ReviewType, date: Date) {
  const { from, to } = reviewPeriod(type, date);
  const [completedTasks, completedProjects, activeProjects, existing] = await Promise.all([
    getCompletedInRange(from, to),
    getCompletedProjectsInRange(from, to),
    getActiveProjects(),
    db.review.findFirst({
      where: { type, date: startOfDay(date), archivedAt: null },
    }),
  ]);
  return { from, to, completedTasks, completedProjects, activeProjects, existing };
}
