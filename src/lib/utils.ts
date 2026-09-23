import {
  differenceInCalendarDays,
  format,
  isPast,
  isToday,
  isTomorrow,
  startOfDay,
} from "date-fns";

/** Merge class names, dropping falsy values. */
export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

/** "D-3", "D-day", "D+2" countdown badge text. */
export function dDay(target: Date | null | undefined): string | null {
  if (!target) return null;
  const diff = differenceInCalendarDays(startOfDay(target), startOfDay(new Date()));
  if (diff === 0) return "D-day";
  return diff > 0 ? `D-${diff}` : `D+${-diff}`;
}

/** True when the date carries a time of day (local midnight = all-day). */
export function hasTimeOfDay(date: Date | null | undefined): boolean {
  if (!date) return false;
  return date.getHours() !== 0 || date.getMinutes() !== 0;
}

/** Human-friendly relative date label for lists, with time when one is set. */
export function friendlyDate(date: Date | null | undefined): string | null {
  if (!date) return null;
  const time = hasTimeOfDay(date) ? ` ${format(date, "h:mm a")}` : "";
  if (isToday(date)) return `Today${time}`;
  if (isTomorrow(date)) return `Tomorrow${time}`;
  return format(date, "MMM d") + time;
}

/** All-day items are overdue after their day ends; timed items after their time passes. */
export function isOverdue(date: Date | null | undefined): boolean {
  if (!date) return false;
  if (hasTimeOfDay(date)) return isPast(date);
  return !isToday(date) && isPast(date);
}

/** First non-empty line of a capture, trimmed to a title-ish length. */
export function deriveTitle(rawText: string, max = 120): string {
  const firstLine = rawText.trim().split(/\r?\n/)[0] ?? "";
  return firstLine.length > max ? `${firstLine.slice(0, max - 1)}…` : firstLine;
}

export function formatDateInput(date: Date | null | undefined): string {
  return date ? format(date, "yyyy-MM-dd") : "";
}

/** Value for an <input type="time">; empty when the date is all-day. */
export function formatTimeInput(date: Date | null | undefined): string {
  return date && hasTimeOfDay(date) ? format(date, "HH:mm") : "";
}

/**
 * Combine date + optional time input values into the string the server
 * schemas parse as local time ("2026-07-07" or "2026-07-07T14:30").
 */
export function joinDateTime(date: string, time: string): string {
  if (!date) return "";
  return time ? `${date}T${time}` : date;
}

/** Parse a "yyyy-MM-dd" input value as LOCAL midnight (new Date(str) parses it as UTC). */
export function parseDateInput(value: string): Date | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/**
 * UI label for what a task is missing, or null when it's fully sorted.
 * Kept in sync with TRIAGE_OR (src/lib/services/tasks.ts).
 */
export function missingDetail(t: {
  status: string;
  context: string | null;
  dueDate: Date | string | null;
  scheduledDate: Date | string | null;
}): string | null {
  if (
    !["waiting", "someday", "completed", "canceled"].includes(t.status) &&
    !t.dueDate &&
    !t.scheduledDate
  ) {
    return "Needs date";
  }
  return null;
}
