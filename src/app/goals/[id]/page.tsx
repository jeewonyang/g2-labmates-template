import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { notFound } from "next/navigation";
import { format } from "date-fns";
import { ArrowLeft } from "lucide-react";
import { getGoal } from "@/lib/services/goals";
import { PageHeader, SectionCard, EmptyState, ProgressBar, Stat } from "@/components/ui/primitives";
import { GoalStatusBadge, ProjectStatusBadge, Badge } from "@/components/ui/Badge";
import { EditGoalButton } from "@/components/forms/EditForms";
import { dDay } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function GoalDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const goal = await getGoal(id);
  if (!goal) notFound();

  return (
    <div>
      <PlannerNav />
      <Link href="/goals" className="mb-3 inline-flex items-center gap-1 text-sm text-[var(--ink-3)] hover:text-[var(--ink)]">
        <ArrowLeft className="h-4 w-4" /> Goals
      </Link>
      <PageHeader
        title={goal.title}
        subtitle={goal.description ?? undefined}
        actions={
          <div className="flex items-center gap-2">
            <GoalStatusBadge status={goal.status} />
            <EditGoalButton
              goal={{
                id: goal.id,
                title: goal.title,
                description: goal.description,
                status: goal.status,
                year: goal.year,
                quarter: goal.quarter,
                targetDate: goal.targetDate,
                areaId: goal.areaId,
              }}
            />
          </div>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Progress" value={goal.progress == null ? "—" : `${Math.round(goal.progress * 100)}%`} />
        <Stat label="Projects" value={goal.projects.length} />
        <Stat label="Period" value={goal.quarter ? `Q${goal.quarter}` : goal.year ?? "—"} />
        <Stat label="Target" value={goal.targetDate ? dDay(new Date(goal.targetDate)) ?? "—" : "—"} hint={goal.targetDate ? format(new Date(goal.targetDate), "MMM d, yyyy") : undefined} />
      </div>

      <div className="mb-5"><ProgressBar value={goal.progress} /></div>

      <SectionCard title={`Linked projects · ${goal.projects.length}`}>
        {goal.projects.length ? (
          <ul className="space-y-3">
            {goal.projects.map((p) => (
              <li key={p.id}>
                <Link href={`/projects/${p.id}`} className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm text-[var(--ink)]">{p.title}</span>
                  <div className="flex items-center gap-2">
                    {p.nextAction && <Badge tone="gray">Next: {p.nextAction.title}</Badge>}
                    <ProjectStatusBadge status={p.status} />
                  </div>
                </Link>
                <div className="mt-1.5"><ProgressBar value={p.progress} /></div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No linked projects" description="Attach projects to this goal to track progress toward it." />
        )}
      </SectionCard>
    </div>
  );
}
