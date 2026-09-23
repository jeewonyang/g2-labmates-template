"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { CalendarArrowDown, LoaderCircle } from "lucide-react";
import { pullOverdueTasksToTodayAction } from "@/lib/actions";
import { Button } from "@/components/ui/primitives";

/**
 * Reset every overdue task to today in one press — action date onto today, and
 * a missed due date with it.
 *
 * The count comes from the server render, like the /ops bulk buttons: it can
 * only move what was on screen when the page rendered, and a task that ages
 * into overdue mid-read waits for the next refresh rather than being swept up
 * silently.
 *
 * The confirm names what actually changes — the action date moves to today,
 * and a missed due date is reset to today with it (the owner, 2026-08-19) —
 * because this rewrites a deadline, and the owner should know that before pressing.
 */
export function PullOverdueButton({ count }: { count: number }) {
  const router = useRouter();
  const [pending, start] = useTransition();

  if (count === 0) return null;

  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={pending}
      className="text-[var(--accent-ink)]"
      onClick={() => {
        if (
          !window.confirm(
            `Reset ${count} overdue task${count === 1 ? "" : "s"} to today? ` +
              `Their action date moves to today, and any missed due date is reset to today.`,
          )
        ) {
          return;
        }
        start(async () => {
          await pullOverdueTasksToTodayAction();
          router.refresh();
        });
      }}
    >
      {pending ? (
        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <CalendarArrowDown className="h-3.5 w-3.5" />
      )}
      Reset {count} overdue to today
    </Button>
  );
}
