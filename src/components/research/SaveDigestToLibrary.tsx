"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { BookmarkPlus, LoaderCircle, MoveRight } from "lucide-react";
import { saveDigestToLibraryAction } from "@/lib/actions";
import {
  BRAINSTORMING_TARGET,
  parseResearchTarget,
  ResearchTargetSelect,
  type ResearchTargetOptions,
} from "@/components/research/ResearchTargetSelect";

/**
 * Keep one paper review from the CEO Brief, filed against a project.
 *
 * The daily research team's digests are read and then lost: dismissing one
 * hides it, and nothing else on the page keeps it. This files the paper in the
 * Rho library exactly as the Research Newsletters card does for an article -
 * same destinations, same "classify later" default - except that the review
 * already exists, so saving runs no model and enqueues no job.
 */
export function SaveDigestToLibrary({
  digestPath,
  saved,
  targets,
}: {
  digestPath: string;
  saved: { targetLabel: string; targetValue: string } | null;
  targets: ResearchTargetOptions;
}) {
  const router = useRouter();
  const [selection, setSelection] = useState(
    saved?.targetValue ?? BRAINSTORMING_TARGET,
  );
  const [error, setError] = useState("");
  const [pending, startTransition] = useTransition();
  const unchanged = saved !== null && selection === saved.targetValue;

  function save() {
    setError("");
    startTransition(async () => {
      try {
        await saveDigestToLibraryAction({
          digestPath,
          ...parseResearchTarget(selection),
        });
        router.refresh();
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : "Could not save this review to the library.",
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
          ariaLabel="File this paper under"
          className="min-w-48 flex-1"
          {...targets}
        />
        <button
          type="button"
          onClick={save}
          disabled={pending || unchanged}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-xs font-medium text-[var(--accent-ink)] hover:bg-[var(--accent-soft)] disabled:opacity-40"
        >
          {pending ? (
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
          ) : saved ? (
            <MoveRight className="h-3.5 w-3.5" />
          ) : (
            <BookmarkPlus className="h-3.5 w-3.5" />
          )}
          {saved ? "Move" : "Save to library"}
        </button>
      </div>
      {saved && (
        <p className="mt-1.5 text-[11px] text-[var(--ink-3)]">
          In the Rho library · {saved.targetLabel} ·{" "}
          <Link href="/research" className="text-[var(--accent-ink)] hover:underline">
            Open library
          </Link>
        </p>
      )}
      {error && (
        <p className="mt-1.5 text-xs text-[var(--red)]" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
