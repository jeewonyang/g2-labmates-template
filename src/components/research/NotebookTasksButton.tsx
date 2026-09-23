"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { ListChecks, Loader2 } from "lucide-react";
import { proposeNotebookTasksAction } from "@/lib/actions";
import { Button } from "@/components/ui/primitives";
import { TaskExtractDialog } from "@/components/tasks/TaskExtractDialog";
import type { TaskCandidate } from "@/lib/services/taskExtract";

/**
 * Set up the next cycle: the entry's next steps become planner tasks under
 * the project, through the same preview every other text-to-tasks path uses.
 * Nothing is created until they keep it.
 */
export function NotebookTasksButton({
  projectCode,
  entryName,
  count,
}: {
  projectCode: string;
  entryName: string;
  count: number;
}) {
  const router = useRouter();
  const [proposal, setProposal] = useState<{
    candidates: TaskCandidate[];
    projects: Array<{ id: string; title: string }>;
  } | null>(null);
  const [created, setCreated] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const propose = () =>
    start(async () => {
      setError(null);
      try {
        setProposal(await proposeNotebookTasksAction(projectCode, entryName));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not read the next steps.");
      }
    });

  return (
    <>
      <Button size="sm" onClick={propose} disabled={pending || count === 0} title="Turn next steps into planner tasks">
        {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ListChecks className="h-3.5 w-3.5" />}
        Plan next cycle{count ? ` (${count})` : ""}
      </Button>
      {created !== null && (
        <span className="text-xs text-[var(--green)]">
          {created} task{created === 1 ? "" : "s"} created
        </span>
      )}
      {error && <span className="text-xs text-[var(--red)]">{error}</span>}
      {proposal && (
        <TaskExtractDialog
          open
          onClose={() => setProposal(null)}
          title={`Next cycle from ${entryName}`}
          candidates={proposal.candidates}
          projects={proposal.projects}
          target={{ status: "next" }}
          onCreated={(n) => {
            setCreated(n);
            router.refresh();
          }}
        />
      )}
    </>
  );
}
