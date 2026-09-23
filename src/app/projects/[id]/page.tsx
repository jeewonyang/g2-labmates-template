import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { notFound } from "next/navigation";
import { format } from "date-fns";
import { ArrowLeft, Target } from "lucide-react";
import { getProject } from "@/lib/services/projects";
import { listAreas } from "@/lib/services/areas";
import {
  PageHeader,
  SectionCard,
  ProgressBar,
  EmptyState,
  Stat,
} from "@/components/ui/primitives";
import { PriorityBadge, NoteTypeBadge, ResourceStatusBadge } from "@/components/ui/Badge";
import { TaskList } from "@/components/tasks/TaskItem";
import { NewTaskButton } from "@/components/forms/CreateForms";
import { ProjectStatusSelect, NextActionSelect } from "@/components/projects/ProjectControls";
import { EditProjectButton } from "@/components/forms/EditForms";
import { dDay } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [project, areas] = await Promise.all([getProject(id), listAreas()]);
  if (!project) notFound();

  const openTasks = project.tasks.filter((t) => t.status !== "completed" && t.status !== "canceled");
  const doneTasks = project.tasks.filter((t) => t.status === "completed");

  return (
    <div>
      <PlannerNav />
      <Link href="/projects" className="mb-3 inline-flex items-center gap-1 text-sm text-[var(--ink-3)] hover:text-[var(--ink)]">
        <ArrowLeft className="h-4 w-4" /> Projects
      </Link>

      <PageHeader
        title={project.title}
        subtitle={project.description ?? undefined}
        actions={
          <div className="flex items-center gap-2">
            <PriorityBadge priority={project.priority} />
            <ProjectStatusSelect id={project.id} status={project.status} />
            <EditProjectButton
              project={{
                id: project.id,
                title: project.title,
                description: project.description,
                priority: project.priority,
                status: project.status,
                startDate: project.startDate,
                targetDate: project.targetDate,
                areaId: project.areaId,
                goalId: project.goalId,
              }}
            />
          </div>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Progress" value={project.progress == null ? "—" : `${Math.round(project.progress * 100)}%`} />
        <Stat label="Open tasks" value={openTasks.length} />
        <Stat label="Notes" value={project.notes.length} />
        <Stat label="Target" value={project.targetDate ? dDay(new Date(project.targetDate)) ?? "—" : "—"} hint={project.targetDate ? format(new Date(project.targetDate), "MMM d, yyyy") : undefined} />
      </div>

      <div className="mb-5"><ProgressBar value={project.progress} /></div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <SectionCard
            title={`Tasks · ${openTasks.length} open`}
            action={
              <NewTaskButton
                defaultProjectId={project.id}
                defaultAreaId={project.areaId ?? undefined}
                areas={areas.map((a) => ({ id: a.id, title: a.title }))}
                label="Add task"
              />
            }
          >
            {openTasks.length ? (
              <TaskList tasks={openTasks} showProject={false} />
            ) : (
              <EmptyState title="No open tasks" description="Add the next concrete step for this project." />
            )}
            {doneTasks.length > 0 && (
              <details className="mt-3 border-t pt-2">
                <summary className="cursor-pointer text-xs text-[var(--ink-3)]">
                  {doneTasks.length} completed
                </summary>
                <div className="mt-1"><TaskList tasks={doneTasks} showProject={false} showHighlight={false} /></div>
              </details>
            )}
          </SectionCard>

          <SectionCard title={`Notes · ${project.notes.length}`}>
            {project.notes.length ? (
              <ul className="divide-y">
                {project.notes.map((n) => (
                  <li key={n.id}>
                    <Link href={`/notes/${n.id}`} className="flex items-center justify-between gap-2 py-2 hover:opacity-80">
                      <span className="truncate text-sm text-[var(--ink)]">{n.title}</span>
                      <NoteTypeBadge type={n.type} />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--ink-3)]">No linked notes.</p>
            )}
          </SectionCard>

          <SectionCard title={`Resources · ${project.resources.length}`}>
            {project.resources.length ? (
              <ul className="divide-y">
                {project.resources.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2 py-2">
                    <Link href={`/resources/${r.id}`} className="truncate text-sm text-[var(--ink)] hover:opacity-80">{r.title}</Link>
                    <ResourceStatusBadge status={r.status} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--ink-3)]">No linked resources.</p>
            )}
          </SectionCard>
        </div>

        <div className="space-y-4">
          <SectionCard title="Next action">
            <NextActionSelect
              projectId={project.id}
              currentId={project.nextActionId}
              tasks={project.tasks.map((t) => ({ id: t.id, title: t.title, status: t.status }))}
            />
            {project.nextAction && (
              <p className="mt-2 text-sm text-[var(--ink-2)]">{project.nextAction.title}</p>
            )}
          </SectionCard>

          <SectionCard title="Details">
            <dl className="space-y-2 text-sm">
              <Row label="Area" value={project.area ? <Link href={`/areas/${project.area.id}`} className="text-[var(--accent-ink)] hover:underline">{project.area.title}</Link> : "—"} />
              <Row
                label="Goal"
                value={
                  project.goal ? (
                    <Link href={`/goals/${project.goal.id}`} className="inline-flex items-center gap-1 text-[var(--accent-ink)] hover:underline">
                      <Target className="h-3.5 w-3.5" />{project.goal.title}
                    </Link>
                  ) : "—"
                }
              />
              <Row label="Start" value={project.startDate ? format(new Date(project.startDate), "MMM d, yyyy") : "—"} />
              <Row label="Target" value={project.targetDate ? format(new Date(project.targetDate), "MMM d, yyyy") : "—"} />
            </dl>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-[var(--ink-3)]">{label}</dt>
      <dd className="text-right text-[var(--ink)]">{value}</dd>
    </div>
  );
}
