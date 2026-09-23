import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { listGoals } from "@/lib/services/goals";
import { listAreas } from "@/lib/services/areas";
import { PageHeader, Card, EmptyState, ProgressBar } from "@/components/ui/primitives";
import { GoalStatusBadge, Badge } from "@/components/ui/Badge";
import { NewGoalButton } from "@/components/forms/CreateForms";
import { EditGoalButton } from "@/components/forms/EditForms";
import { dDay } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function GoalsPage() {
  const [goals, areas] = await Promise.all([listGoals(), listAreas()]);

  // Group by year desc.
  const byYear = new Map<number, typeof goals>();
  for (const g of goals) {
    const y = g.year ?? 0;
    if (!byYear.has(y)) byYear.set(y, []);
    byYear.get(y)!.push(g);
  }
  const years = [...byYear.keys()].sort((a, b) => b - a);

  return (
    <div>
      <PlannerNav />
      <PageHeader
        title="Goals"
        subtitle="Longer-term targets that connect to your projects."
        actions={
          <>
            <Link href="/areas" className="text-sm text-[var(--accent-ink)] hover:underline">
              Areas
            </Link>
            <NewGoalButton areas={areas.map((a) => ({ id: a.id, title: a.title }))} />
          </>
        }
      />

      {goals.length === 0 ? (
        <EmptyState title="No goals yet" description="Set a longer-term target and link projects to it." />
      ) : (
        <div className="space-y-6">
          {years.map((year) => (
            <div key={year}>
              <h2 className="mb-2 text-sm font-semibold text-[var(--ink-2)]">{year || "Undated"}</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {byYear.get(year)!.map((g) => (
                  <Card key={g.id} className="group h-full p-4">
                    <div className="flex items-start justify-between gap-2">
                      <Link
                        href={`/goals/${g.id}`}
                        className="font-medium text-[var(--ink)] hover:text-[var(--accent-ink)]"
                      >
                        {g.title}
                      </Link>
                      <div className="flex shrink-0 items-center gap-1">
                        <GoalStatusBadge status={g.status} />
                        <EditGoalButton
                          goal={{
                            id: g.id,
                            title: g.title,
                            description: g.description,
                            status: g.status,
                            year: g.year,
                            quarter: g.quarter,
                            targetDate: g.targetDate,
                            areaId: g.areaId,
                          }}
                          iconOnly
                        />
                      </div>
                    </div>
                    <div className="mt-3"><ProgressBar value={g.progress} /></div>
                    <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-xs text-[var(--ink-3)]">
                      {g.quarter && <Badge tone="purple">Q{g.quarter}</Badge>}
                      <span>{g.projects.length} projects</span>
                      {g.targetDate && <span>· {dDay(new Date(g.targetDate))}</span>}
                      {g.area && <span>· {g.area.title}</span>}
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
