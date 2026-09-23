import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { getArea } from "@/lib/services/areas";
import { PageHeader, SectionCard, EmptyState, ProgressBar, Stat } from "@/components/ui/primitives";
import { HealthBadge, ProjectStatusBadge, NoteTypeBadge, ResourceStatusBadge, GoalStatusBadge } from "@/components/ui/Badge";
import { TaskList } from "@/components/tasks/TaskItem";
import { EditAreaButton } from "@/components/forms/EditForms";

export const dynamic = "force-dynamic";

export default async function AreaDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const area = await getArea(id);
  if (!area) notFound();

  return (
    <div>
      <PlannerNav />
      <Link href="/areas" className="mb-3 inline-flex items-center gap-1 text-sm text-[var(--ink-3)] hover:text-[var(--ink)]">
        <ArrowLeft className="h-4 w-4" /> Areas
      </Link>
      <PageHeader
        title={area.title}
        subtitle={area.description ?? undefined}
        actions={
          <div className="flex items-center gap-2">
            {area.type === "area" && <HealthBadge health={area.health} />}
            <EditAreaButton
              area={{
                id: area.id,
                title: area.title,
                description: area.description,
                type: area.type,
                health: area.health,
              }}
            />
          </div>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Projects" value={area.projects.length} />
        <Stat label="Open tasks" value={area.tasks.length} />
        <Stat label="Notes" value={area.notes.length} />
        <Stat label="Resources" value={area.resources.length} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title={`Projects · ${area.projects.length}`}>
          {area.projects.length ? (
            <ul className="space-y-3">
              {area.projects.map((p) => (
                <li key={p.id}>
                  <Link href={`/projects/${p.id}`} className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm text-[var(--ink)]">{p.title}</span>
                    <ProjectStatusBadge status={p.status} />
                  </Link>
                  <div className="mt-1.5"><ProgressBar value={p.progress} /></div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No projects" />
          )}
        </SectionCard>

        <SectionCard title={`Open tasks · ${area.tasks.length}`}>
          {area.tasks.length ? (
            <TaskList tasks={area.tasks} />
          ) : (
            <EmptyState title="No open tasks" />
          )}
        </SectionCard>

        {area.goals.length > 0 && (
          <SectionCard title={`Goals · ${area.goals.length}`}>
            <ul className="divide-y">
              {area.goals.map((g) => (
                <li key={g.id}>
                  <Link href={`/goals/${g.id}`} className="flex items-center justify-between gap-2 py-2 hover:opacity-80">
                    <span className="truncate text-sm text-[var(--ink)]">{g.title}</span>
                    <GoalStatusBadge status={g.status} />
                  </Link>
                </li>
              ))}
            </ul>
          </SectionCard>
        )}

        <SectionCard title={`Notes · ${area.notes.length}`}>
          {area.notes.length ? (
            <ul className="divide-y">
              {area.notes.map((n) => (
                <li key={n.id}>
                  <Link href={`/notes/${n.id}`} className="flex items-center justify-between gap-2 py-2 hover:opacity-80">
                    <span className="truncate text-sm text-[var(--ink)]">{n.title}</span>
                    <NoteTypeBadge type={n.type} />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No notes" />
          )}
        </SectionCard>

        <SectionCard title={`Resources · ${area.resources.length}`}>
          {area.resources.length ? (
            <ul className="divide-y">
              {area.resources.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-2 py-2">
                  <Link href={`/resources/${r.id}`} className="truncate text-sm text-[var(--ink)] hover:opacity-80">{r.title}</Link>
                  <ResourceStatusBadge status={r.status} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No resources" />
          )}
        </SectionCard>
      </div>
    </div>
  );
}
