"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Archive, LoaderCircle, MoveRight } from "lucide-react";
import {
  archiveBibliographyItemAction,
  reclassifyBibliographyItemAction,
} from "@/lib/actions";
import {
  parseResearchTarget,
  ResearchTargetSelect,
  type ResearchTargetOption,
} from "@/components/research/ResearchTargetSelect";

type TargetOption = ResearchTargetOption;

export function BibliographyActions({
  itemId,
  currentTarget,
  projects,
  resources,
  areas,
}: {
  itemId: string;
  currentTarget: string;
  projects: TargetOption[];
  resources: TargetOption[];
  areas: TargetOption[];
}) {
  const router = useRouter();
  const [selection, setSelection] = useState(currentTarget);
  const [error, setError] = useState("");
  const [pending, startTransition] = useTransition();

  function move() {
    if (selection === currentTarget) return;
    setError("");
    startTransition(async () => {
      try {
        await reclassifyBibliographyItemAction({
          itemId,
          ...parseResearchTarget(selection),
        });
        router.refresh();
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : "Could not move this bibliography entry.",
        );
      }
    });
  }

  function archive() {
    if (
      !window.confirm(
        "Archive this paper from the bibliography? Its event history and review report will be retained.",
      )
    ) {
      return;
    }
    setError("");
    startTransition(async () => {
      try {
        await archiveBibliographyItemAction(itemId);
        router.refresh();
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : "Could not remove this bibliography entry.",
        );
      }
    });
  }

  return (
    <div className="mt-3 border-t pt-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <ResearchTargetSelect
          value={selection}
          onChange={setSelection}
          disabled={pending}
          ariaLabel="Move bibliography entry"
          projects={projects}
          resources={resources}
          areas={areas}
        />
        <button
          type="button"
          onClick={move}
          disabled={pending || selection === currentTarget}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-xs font-medium text-[var(--accent-ink)] hover:bg-[var(--accent-soft)] disabled:opacity-40"
        >
          {pending ? (
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <MoveRight className="h-3.5 w-3.5" />
          )}
          Move
        </button>
        <button
          type="button"
          onClick={archive}
          disabled={pending}
          className="ml-auto inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs text-[var(--ink-3)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] disabled:opacity-40"
        >
          <Archive className="h-3.5 w-3.5" />
          Archive
        </button>
      </div>
      {error && (
        <p className="mt-1.5 text-xs text-[var(--red)]" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
