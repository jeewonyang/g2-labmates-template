"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { format } from "date-fns";
import { BookOpen, ExternalLink, LoaderCircle, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { JournalFeed } from "@/lib/services/journals";
import {
  getResearchReviewStatusAction,
  requestPaperReviewAction,
} from "@/lib/actions";
import type {
  ResearchReviewLaunch,
  ResearchReviewStatus,
} from "@/lib/services/research";

/** Compact, tabbed reader for live publisher research feeds. */
export function ResearchTrends({
  feeds,
  projects,
  resources,
}: {
  feeds: JournalFeed[];
  projects: Array<{ id: string; title: string }>;
  resources: Array<{ id: string; title: string }>;
}) {
  const router = useRouter();
  const firstWorking = feeds.find((f) => !f.error)?.key ?? feeds[0]?.key;
  const [active, setActive] = useState(firstWorking);
  const [targetType, setTargetType] = useState<"" | "project" | "resource">("");
  const [targetId, setTargetId] = useState("");
  const [doi, setDoi] = useState("");
  const [lastDoiKey, setLastDoiKey] = useState("");
  const [runs, setRuns] = useState<
    Record<string, ResearchReviewLaunch & { detail?: ResearchReviewStatus | null }>
  >({});
  const [error, setError] = useState("");
  const [isPending, startTransition] = useTransition();
  const feed = feeds.find((f) => f.key === active);
  const core = feeds.filter((item) => item.group === "core");
  const specialty = feeds.filter((item) => item.group === "specialty");
  const targets =
    targetType === "project"
      ? projects
      : targetType === "resource"
        ? resources
        : [];

  useEffect(() => {
    const activeRuns = Object.entries(runs).filter(
      ([, run]) =>
        run.jobId && ["created", "claimed"].includes(run.detail?.status ?? run.status),
    );
    if (!activeRuns.length) return;
    const timer = window.setInterval(() => {
      void Promise.all(
        activeRuns.map(async ([key, run]) => {
          const detail = run.jobId
            ? await getResearchReviewStatusAction(run.jobId)
            : null;
          if (detail?.status === "completed" && run.detail?.status !== "completed") {
            router.refresh();
          }
          setRuns((current) => ({
            ...current,
            [key]: { ...current[key], detail },
          }));
        }),
      );
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [router, runs]);

  function launch(
    key: string,
    request:
      | { source: "doi"; doi: string }
      | { source: "feed"; feedKey: string; sourceRef: string },
  ) {
    if (targetType && !targetId) {
      setError(`Choose the ${targetType} this paper belongs to.`);
      return;
    }
    setError("");
    if (request.source === "doi") setLastDoiKey(key);
    startTransition(async () => {
      try {
        const result = await requestPaperReviewAction({
          clientRequestId: window.crypto.randomUUID(),
          ...(targetType && targetId ? { targetType, targetId } : {}),
          ...request,
        });
        setRuns((current) => ({ ...current, [key]: result }));
        if (request.source === "doi") setDoi("");
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Rho could not start the review.");
      }
    });
  }

  function runLabel(
    run:
      | (ResearchReviewLaunch & { detail?: ResearchReviewStatus | null })
      | undefined,
  ) {
    if (!run) return "Review + save";
    if (run.savedOnly) return "Saved";
    const status = run.detail?.status ?? run.status;
    if (status === "created") return "Queued";
    if (status === "claimed") return "Reviewing";
    if (status === "completed") return "View summary";
    if (status === "failed") return "Retry";
    return "Saved";
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border bg-[var(--surface-2)] p-2">
        <select
          value={targetType}
          onChange={(event) => {
            setTargetType(
              event.target.value as "" | "project" | "resource",
            );
            setTargetId("");
          }}
          aria-label="Bibliography target type"
          className="min-w-52 rounded-[var(--radius-sm)] border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
        >
          <option value="">Brainstorming · classify later</option>
          <option value="project">Project</option>
          <option value="resource">Resource</option>
        </select>
        {targetType && (
          <select
            value={targetId}
            onChange={(event) => setTargetId(event.target.value)}
            aria-label={`Bibliography ${targetType}`}
            className="min-w-44 rounded-[var(--radius-sm)] border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
          >
            <option value="">Choose {targetType}…</option>
            {targets.map((target) => (
              <option key={target.id} value={target.id}>
                {target.title}
              </option>
            ))}
          </select>
        )}
        <input
          value={doi}
          onChange={(event) => setDoi(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && doi.trim() && !isPending) {
              launch(`doi:${doi.trim().toLowerCase()}`, {
                source: "doi",
                doi: doi.trim(),
              });
            }
          }}
          placeholder="Paste a DOI to review"
          aria-label="Paper DOI"
          className="min-w-52 flex-1 rounded-[var(--radius-sm)] border bg-[var(--surface)] px-2.5 py-1.5 text-xs text-[var(--ink)] placeholder:text-[var(--ink-3)]"
        />
        <button
          type="button"
          disabled={!doi.trim() || isPending}
          onClick={() =>
            launch(`doi:${doi.trim().toLowerCase()}`, {
              source: "doi",
              doi: doi.trim(),
            })
          }
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          {isPending ? (
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Sparkles className="h-3.5 w-3.5" />
          )}
          Ask Rho
        </button>
        <Link
          href="/research"
          className="inline-flex items-center gap-1 text-xs text-[var(--accent-ink)] hover:underline"
        >
          <BookOpen className="h-3.5 w-3.5" />
          Rho library
        </Link>
      </div>
      {error && (
        <p className="mb-2 text-xs text-[var(--red)]" role="alert">
          {error}
        </p>
      )}
      {lastDoiKey && runs[lastDoiKey] && (
        <div className="mb-2 flex items-center gap-2 rounded-[var(--radius-sm)] border bg-[var(--surface-2)] px-2.5 py-2 text-xs text-[var(--ink-2)]">
          <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" />
          <span className="flex-1">
            DOI saved · {runLabel(runs[lastDoiKey])}
          </span>
          {runs[lastDoiKey].detail?.digestPath && (
            <Link
              href={`/vault/${runs[lastDoiKey].detail?.digestPath}`}
              className="font-medium text-[var(--accent-ink)] hover:underline"
            >
              Open summary
            </Link>
          )}
        </div>
      )}
      <div className="mb-3 space-y-1.5" role="tablist" aria-label="Journals">
        <JournalTabs feeds={core} active={active} onSelect={setActive} />
        <div className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--ink-3)]">
            More
          </span>
          <div className="min-w-0 flex-1">
            <JournalTabs feeds={specialty} active={active} onSelect={setActive} />
          </div>
        </div>
      </div>

      {!feed || feed.error ? (
        <p className="py-4 text-sm text-[var(--ink-3)]">
          Couldn&apos;t load this feed right now.{" "}
          {feed && (
            <a href={feed.homepage} target="_blank" rel="noreferrer" className="text-[var(--accent-ink)] hover:underline">
              Open {feed.label} directly
            </a>
          )}
        </p>
      ) : (
        <ul className="divide-y">
          {feed.items.map((item, i) => (
            <li key={i} className="py-2.5">
              <div className="flex items-start gap-2">
                <a
                  href={item.link || feed.homepage}
                  target="_blank"
                  rel="noreferrer"
                  className="group min-w-0 flex-1"
                >
                  <span className="flex items-start gap-1.5 text-sm font-medium text-[var(--ink)] group-hover:text-[var(--accent-ink)]">
                    <span className="flex-1">{item.title}</span>
                    <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--ink-3)] opacity-0 transition-opacity group-hover:opacity-100" />
                  </span>
                {(item.publishedAt || item.summary) && (
                  <span className="mt-0.5 line-clamp-1 block text-xs leading-relaxed text-[var(--ink-3)]">
                    {item.publishedAt && (
                      <span className="font-medium text-[var(--ink-2)]">
                        {format(new Date(item.publishedAt), "MMM d, yyyy")}
                      </span>
                    )}
                    {item.publishedAt && item.summary && " · "}
                    {item.summary}
                  </span>
                )}
                </a>
                {runs[item.link]?.detail?.status === "completed" &&
                runs[item.link]?.detail?.digestPath ? (
                  <Link
                    href={`/vault/${runs[item.link].detail?.digestPath}`}
                    className="shrink-0 rounded-[var(--radius-sm)] border border-[var(--green)]/30 bg-[var(--green-soft)] px-2 py-1 text-[11px] font-medium text-[var(--green)]"
                  >
                    {runLabel(runs[item.link])}
                  </Link>
                ) : (
                  <button
                    type="button"
                    disabled={
                      isPending ||
                      ["created", "claimed"].includes(
                        runs[item.link]?.detail?.status ?? runs[item.link]?.status ?? "",
                      )
                    }
                    onClick={() =>
                      launch(item.link, {
                        source: "feed",
                        feedKey: feed.key,
                        sourceRef: item.link,
                      })
                    }
                    className="shrink-0 rounded-[var(--radius-sm)] border px-2 py-1 text-[11px] font-medium text-[var(--accent-ink)] transition-colors hover:bg-[var(--accent-soft)] disabled:opacity-50"
                  >
                    {runLabel(runs[item.link])}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function JournalTabs({
  feeds,
  active,
  onSelect,
}: {
  feeds: JournalFeed[];
  active: string | undefined;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="flex min-w-0 flex-wrap gap-1">
      {feeds.map((feed) => (
        <button
          key={feed.key}
          role="tab"
          aria-selected={active === feed.key}
          onClick={() => onSelect(feed.key)}
          className={cn(
            "whitespace-nowrap rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs font-medium transition-colors",
            active === feed.key
              ? "bg-[var(--accent-soft)] text-[var(--accent-ink)]"
              : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
          )}
        >
          {feed.label}
          {feed.error && <span className="sr-only"> (temporarily unavailable)</span>}
        </button>
      ))}
    </div>
  );
}
