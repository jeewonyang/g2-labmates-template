import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { listProjects } from "@/lib/services/projects";
import { listAreas } from "@/lib/services/areas";
import { listGoals } from "@/lib/services/goals";
import { PageHeader, EmptyState, ProgressBar, Card } from "@/components/ui/primitives";
import { PriorityBadge } from "@/components/ui/Badge";
import { NewProjectButton } from "@/components/forms/CreateForms";
import { EditProjectButton } from "@/components/forms/EditForms";
import { PROJECT_STATUS_META, type ProjectStatus } from "@/lib/types";
import { dDay } from "@/lib/utils";

export const dynamic = "force-dynamic";

const GROUP_ORDER: ProjectStatus[] = ["active", "paused", "inbox", "completed"];

export default async function ProjectsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const [projects, areas, goals] = await Promise.all([listProjects(), listAreas(), listGoals()]);

  const grouped = new Map<string, typeof projects>();
  for (const status of GROUP_ORDER) grouped.set(status, []);
  for (const p of projects) {
    const key = GROUP_ORDER.includes(p.status as ProjectStatus) ? p.status : "active";
    grouped.get(key)!.push(p);
  }

  return (
    <div>
      <PlannerNav />
      <PageHeader
        title="Projects"
        subtitle="Active outcomes you're working toward, grouped by status."
        actions={
          <NewProjectButton
            areas={areas.map((a) => ({ id: a.id, title: a.title }))}
            goals={goals.map((g) => ({ id: g.id, title: g.title }))}
            openOnMount={sp.new === "1"}
          />
        }
      />

      {projects.length === 0 ? (
        <EmptyState title="No projects yet" description="Create your first project to start organizing outcomes and next actions." />
      ) : (
        <div className="space-y-6">
          {GROUP_ORDER.map((status) => {
            const list = grouped.get(status)!;
            if (!list.length) return null;
            return (
              <div key={status}>
                <h2 className="mb-2 text-sm font-semibold text-[var(--ink-2)]">
                  {PROJECT_STATUS_META[status].label}
                  <span className="ml-1.5 text-[var(--ink-3)]">{list.length}</span>
                </h2>
                <div className="grid gap-3 sm:grid-cols-2">
                  {list.map((p) => (
                    <Card key={p.id} className="group h-full p-4">
                      <div className="flex items-start justify-between gap-2">
                        <Link
                          href={`/projects/${p.id}`}
                          className="font-medium text-[var(--ink)] hover:text-[var(--accent-ink)]"
                        >
                          {p.title}
                        </Link>
                        <div className="flex shrink-0 items-center gap-1">
                          <PriorityBadge priority={p.priority} />
                          <EditProjectButton
                            project={{
                              id: p.id,
                              title: p.title,
                              description: p.description,
                              priority: p.priority,
                              status: p.status,
                              startDate: p.startDate,
                              targetDate: p.targetDate,
                              areaId: p.areaId,
                              goalId: p.goalId,
                            }}
                            iconOnly
                          />
                        </div>
                      </div>
                      {p.description && (
                        <p className="mt-1 line-clamp-2 text-sm text-[var(--ink-3)]">{p.description}</p>
                      )}
                      <div className="mt-3"><ProgressBar value={p.progress} /></div>
                      <div className="mt-2.5 flex items-center gap-2 text-xs text-[var(--ink-3)]">
                        {p.area && <span>{p.area.title}</span>}
                        {p.targetDate && <span>· {dDay(new Date(p.targetDate))}</span>}
                        {p.nextAction && p.nextAction.status !== "completed" && (
                          <span className="truncate">· Next: {p.nextAction.title}</span>
                        )}
                      </div>
                    </Card>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
