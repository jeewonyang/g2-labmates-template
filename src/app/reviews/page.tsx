import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { format } from "date-fns";
import { CheckCircle2, FolderCheck } from "lucide-react";
import { getReviewContext, listReviews } from "@/lib/services/reviews";
import { PageHeader, SectionCard, EmptyState } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/Badge";
import { ReviewComposer } from "@/components/reviews/ReviewComposer";
import { REVIEW_TYPE_META, REVIEW_TYPES, type ReviewType } from "@/lib/types";
import { formatDateInput } from "@/lib/utils";

export const dynamic = "force-dynamic";

function isReviewType(v: string | undefined): v is ReviewType {
  return !!v && (REVIEW_TYPES as readonly string[]).includes(v);
}

export default async function ReviewsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const type: ReviewType = isReviewType(sp.type) ? sp.type : "weekly";
  const date = sp.date ? new Date(sp.date) : new Date();

  const [ctx, history] = await Promise.all([
    getReviewContext(type, date),
    listReviews(),
  ]);

  return (
    <div>
      <PlannerNav />
      <PageHeader
        title="Reviews"
        subtitle="Reflect on your day, week, month, or quarter — and keep the history."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <SectionCard
            title={`${REVIEW_TYPE_META[type].label} review — ${format(date, "MMM d, yyyy")}`}
          >
            {/*
              Keyed on type+date: the composer seeds its state from these props,
              and without a key React reuses the instance across navigation, so
              clicking a History entry changed the title but not the fields —
              and a save would then write the old text to the new date.
            */}
            <ReviewComposer
              key={`${type}:${formatDateInput(date)}`}
              initialType={type}
              initialDate={formatDateInput(date)}
              existing={
                ctx.existing
                  ? {
                      type: ctx.existing.type,
                      date: formatDateInput(ctx.existing.date),
                      wins: ctx.existing.wins,
                      challenges: ctx.existing.challenges,
                      lessons: ctx.existing.lessons,
                      priorities: ctx.existing.priorities,
                      contentMarkdown: ctx.existing.contentMarkdown,
                    }
                  : null
              }
            />
          </SectionCard>
        </div>

        <div className="space-y-4">
          <SectionCard
            title={
              <span className="flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-[var(--green)]" />
                Completed this period
              </span>
            }
          >
            <p className="mb-2 text-xs text-[var(--ink-3)]">
              {format(ctx.from, "MMM d")} – {format(ctx.to, "MMM d")}
            </p>
            {ctx.completedTasks.length ? (
              <ul className="space-y-1.5">
                {ctx.completedTasks.slice(0, 12).map((t) => (
                  <li key={t.id} className="truncate text-sm text-[var(--ink-2)]">✓ {t.title}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--ink-3)]">No tasks completed in this period.</p>
            )}
            {ctx.completedProjects.length > 0 && (
              <div className="mt-3 border-t pt-2">
                <p className="mb-1 flex items-center gap-1 text-xs font-medium text-[var(--ink-2)]">
                  <FolderCheck className="h-3.5 w-3.5" /> Projects completed
                </p>
                {ctx.completedProjects.map((p) => (
                  <p key={p.id} className="truncate text-sm text-[var(--ink-2)]">✓ {p.title}</p>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title={`Active projects · ${ctx.activeProjects.length}`}>
            {ctx.activeProjects.length ? (
              <ul className="space-y-1.5">
                {ctx.activeProjects.map((p) => (
                  <li key={p.id}>
                    <Link href={`/projects/${p.id}`} className="block truncate text-sm text-[var(--ink-2)] hover:text-[var(--accent-ink)]">
                      {p.title}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--ink-3)]">No active projects.</p>
            )}
          </SectionCard>
        </div>
      </div>

      <div className="mt-6">
        <h2 className="mb-2 text-sm font-semibold text-[var(--ink-2)]">History</h2>
        {history.length ? (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {history.map((r) => (
              <Link
                key={r.id}
                href={`/reviews?type=${r.type}&date=${formatDateInput(r.date)}`}
                className="flex items-center justify-between gap-2 rounded-[var(--radius-sm)] border bg-[var(--surface)] px-3 py-2 text-sm shadow-[var(--shadow-sm)] hover:bg-[var(--surface-hover)]"
              >
                <span className="text-[var(--ink)]">{format(new Date(r.date), "MMM d, yyyy")}</span>
                <Badge tone="gray">{REVIEW_TYPE_META[r.type as ReviewType]?.label ?? r.type}</Badge>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState title="No reviews yet" description="Complete your first review above to start building a history." />
        )}
      </div>
    </div>
  );
}
