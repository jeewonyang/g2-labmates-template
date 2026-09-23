"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle, Trash2 } from "lucide-react";
import { clearCompletedTasksAction } from "@/lib/actions";
import { Button } from "@/components/ui/primitives";

/**
 * Sweep every completed task off the active lists at once.
 *
 * "Delete" here means archive, same as the per-task trash icon — the rows stay
 * on /archive. The confirm spells that out and names the count, because this is
 * the only control in the app that can move hundreds of rows in one click.
 */
export function ClearCompletedButton({ count }: { count: number }) {
  const router = useRouter();
  const [pending, start] = useTransition();

  if (count === 0) return null;

  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={pending}
      className="text-[var(--red)]"
      onClick={() => {
        if (
          !window.confirm(
            `Clear ${count} completed task${count === 1 ? "" : "s"}? They move to the archive and stay recoverable.`,
          )
        ) {
          return;
        }
        start(async () => {
          await clearCompletedTasksAction();
          router.refresh();
        });
      }}
    >
      {pending ? (
        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Trash2 className="h-3.5 w-3.5" />
      )}
      Clear all completed
    </Button>
  );
}
