"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import {
  ArrowRight,
  BriefcaseBusiness,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  FlaskConical,
  RotateCcw,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button, LinkButton } from "@/components/ui/primitives";
import { CollapsibleSectionCard } from "@/components/ui/CollapsibleCard";
import { SaveDigestToLibrary } from "@/components/research/SaveDigestToLibrary";
import type { ResearchTargetOptions } from "@/components/research/ResearchTargetSelect";
import type {
  DailyExecutiveBrief,
  ExecutiveDigest,
} from "@/lib/services/executive-digest";
import type { DigestLibraryEntry } from "@/lib/services/research";

const COLLAPSED_KEY = "second-brain:ceo-brief:collapsed";

const TONE = {
  attention: { badge: "amber" as const, border: "border-l-[var(--amber)]" },
  watch: { badge: "blue" as const, border: "border-l-[var(--blue)]" },
  update: { badge: "accent" as const, border: "border-l-[var(--accent)]" },
};

const TONE_PRIORITY: Record<ExecutiveDigest["tone"], number> = {
  attention: 0,
  watch: 1,
  update: 2,
};

function executiveOrder(items: ExecutiveDigest[]) {
  return [...items].sort(
    (a, b) =>
      TONE_PRIORITY[a.tone] - TONE_PRIORITY[b.tone] ||
      b.updatedIso.localeCompare(a.updatedIso),
  );
}

function vaultHref(relPath: string): string {
  return `/vault/${relPath.split("/").map(encodeURIComponent).join("/")}`;
}

export function ExecutiveBriefClient({
  brief,
  library,
  targets,
}: {
  brief: DailyExecutiveBrief;
  /** Digest path -> where that paper is already filed in the Rho library. */
  library: Record<string, DigestLibraryEntry>;
  targets: ResearchTargetOptions;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const reportKeys = useMemo(
    () =>
      [...brief.attention, ...brief.research].map(
        (item) => item.key,
      ),
    [brief.attention, brief.research],
  );
  const [collapsed, setCollapsed] = useState<Set<string>>(
    () => new Set(reportKeys),
  );
  const [showDismissed, setShowDismissed] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(COLLAPSED_KEY);
      if (!stored) return;
      const saved = JSON.parse(stored);
      if (Array.isArray(saved)) {
        setCollapsed(new Set(saved.filter((key) => typeof key === "string")));
      }
    } catch {
      // A corrupt preference should never block the daily briefing.
    }
  }, []);

  const sections = useMemo(
    () => [
      {
        id: "research",
        title: "Scientific Research",
        icon: FlaskConical,
        items: brief.research,
      },
    ],
    [brief.research],
  );

  function toggle(key: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]));
      return next;
    });
  }

  function collapseAll() {
    const next = new Set(reportKeys);
    setCollapsed(next);
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify(reportKeys));
  }

  function post(action: "dismiss" | "restore", key?: string) {
    startTransition(async () => {
      const response = await fetch("/api/ceo-brief", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, key }),
      });
      if (response.ok) router.refresh();
    });
  }

  const visibleAttention = executiveOrder(
    brief.attention.filter((item) => showDismissed || !item.dismissed),
  );
  const hasReports =
    brief.research.length > 0 ||
    brief.attention.length > 0;

  return (
    // Same fold affordance as every other minimizable card on /today: the
    // chevron on the header title, state in localStorage. This card used to
    // carry its own Minimize/Expand button and its own preference key, which
    // meant two different controls for one idea on a single page.
    <CollapsibleSectionCard
      storageKey="today-ceo-brief"
      title={
        <span className="flex items-center gap-1.5">
          <BriefcaseBusiness className="h-4 w-4 text-[var(--accent)]" />
          CEO Brief
        </span>
      }
      action={
        <Link
          href="/teams"
          className="px-2 text-xs text-[var(--accent-ink)] hover:underline"
        >
          Team office
        </Link>
      }
      bodyClassName="p-0"
    >
      {hasReports ? (
        <div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5">
        <p className="text-xs text-[var(--ink-3)]">
          What matters now, why it matters, and the minimum evidence needed to act.
        </p>
        <div className="flex flex-wrap items-center gap-1">
          {brief.dismissedCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowDismissed((value) => !value)}
            >
              {showDismissed ? (
                <EyeOff className="h-3.5 w-3.5" />
              ) : (
                <Eye className="h-3.5 w-3.5" />
              )}
              {showDismissed ? "Hide dismissed" : `Show dismissed (${brief.dismissedCount})`}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={collapseAll}>
            Collapse all
          </Button>
          {brief.dismissedCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              disabled={pending}
              onClick={() => post("restore")}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Restore
            </Button>
          )}
        </div>
      </div>

      {visibleAttention.length > 0 && (
        <section className="border-b bg-[var(--amber-soft)]/40 p-3 sm:p-4">
          <p className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--amber)]">
            Needs attention
          </p>
          <div className="space-y-2">
            {visibleAttention.map((digest) => (
              <DigestRow
                key={digest.key}
                digest={digest}
                collapsed={collapsed.has(digest.key)}
                pending={pending}
                saved={library[digest.relPath] ?? null}
                targets={targets}
                onToggle={() => toggle(digest.key)}
                onDismiss={() => post("dismiss", digest.key)}
              />
            ))}
          </div>
        </section>
      )}

      <div className="grid divide-y lg:grid-cols-2 lg:divide-x lg:divide-y-0">
        {sections.map(({ id, title, icon: Icon, items }) => {
          const visible = executiveOrder(
            items.filter((item) => showDismissed || !item.dismissed),
          );
          return (
            <section key={id} className="min-w-0 p-3 sm:p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
                  <Icon className="h-4 w-4 text-[var(--accent)]" />
                  {title}
                </h3>
                {items[0] && (
                  <span className="font-mono text-[10px] text-[var(--ink-3)]">
                    {items[0].reportDate}
                  </span>
                )}
              </div>
              {visible.length ? (
                <div className="space-y-2">
                  {visible.map((digest) => (
                    <DigestRow
                      key={digest.key}
                      digest={digest}
                      collapsed={collapsed.has(digest.key)}
                      pending={pending}
                      saved={library[digest.relPath] ?? null}
                      targets={targets}
                      onToggle={() => toggle(digest.key)}
                      onDismiss={() => post("dismiss", digest.key)}
                    />
                  ))}
                </div>
              ) : (
                <p className="rounded-[var(--radius-sm)] border border-dashed px-3 py-4 text-sm text-[var(--ink-3)]">
                  {items.length ? "All reports dismissed." : "No report available yet."}
                </p>
              )}
            </section>
          );
        })}
      </div>
        </div>
      ) : (
        <div className="px-5 py-6">
          <p className="text-sm font-medium text-[var(--ink)]">
            No team reports yet
          </p>
          <p className="mt-1 text-sm text-[var(--ink-3)]">
            Scientific Research will appear here after the research team&apos;s
            next run.
          </p>
        </div>
      )}
    </CollapsibleSectionCard>
  );
}

function DigestRow({
  digest,
  collapsed,
  pending,
  saved,
  targets,
  onToggle,
  onDismiss,
}: {
  digest: ExecutiveDigest;
  collapsed: boolean;
  pending: boolean;
  saved: DigestLibraryEntry | null;
  targets: ResearchTargetOptions;
  onToggle: () => void;
  onDismiss: () => void;
}) {
  const tone = TONE[digest.tone];
  return (
    <article
      className={`rounded-[var(--radius-sm)] border border-l-2 bg-[var(--surface)] ${
        tone.border
      } ${digest.dismissed ? "opacity-55" : ""}`}
    >
      <div className="p-3">
        <div className="flex items-center gap-2">
          <Badge tone={tone.badge}>{digest.signal}</Badge>
          <span className="text-[11px] text-[var(--ink-3)]">
            Updated{" "}
            {formatDistanceToNow(new Date(digest.updatedIso), { addSuffix: true })}
          </span>
          <div className="ml-auto flex items-center gap-0.5">
            <button
              type="button"
              onClick={onToggle}
              aria-label={collapsed ? "Expand report" : "Collapse report"}
              className="rounded p-1 text-[var(--ink-3)] hover:bg-[var(--surface-hover)]"
            >
              {collapsed ? (
                <ChevronRight className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </button>
            <button
              type="button"
              onClick={onDismiss}
              disabled={pending || digest.dismissed}
              aria-label="Dismiss report"
              title="Dismiss until this report changes"
              className="rounded p-1 text-[var(--ink-3)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] disabled:opacity-40"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="mt-2 block w-full min-w-0 text-left"
        >
          <h4 className="line-clamp-2 text-base font-semibold leading-snug text-[var(--ink)] sm:text-[17px]">
            {digest.reportTitle}
          </h4>
          <p className="mt-2 line-clamp-2 text-sm font-normal leading-relaxed text-[var(--ink-2)]">
            <span className="sr-only">Bottom line: </span>
            {digest.headline}
          </p>
        </button>
      </div>

      {!collapsed && (
        <div className="border-t px-3 pb-3 pt-2.5">
          {digest.highlights.length > 0 && (
            <>
              <p className="mb-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--ink-3)]">
                Decision support
              </p>
              <ul className="space-y-1.5">
                {digest.highlights.map((highlight) => (
                  <li
                    key={highlight}
                    className="flex items-start gap-2 text-[13px] leading-relaxed text-[var(--ink-2)]"
                  >
                    <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                    <span>{highlight}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="mt-3">
            <LinkButton href={vaultHref(digest.relPath)} variant="ghost" size="sm">
              Read full report
              <ArrowRight className="h-3.5 w-3.5" />
            </LinkButton>
          </div>
          {/*
            Only a paper review can be filed: a project pulse or a meeting
            digest has no citation, and a picker that cannot work is worse than
            no picker.
          */}
          {digest.paperDigest && (
            <SaveDigestToLibrary
              digestPath={digest.relPath}
              saved={saved}
              targets={targets}
            />
          )}
        </div>
      )}
    </article>
  );
}
