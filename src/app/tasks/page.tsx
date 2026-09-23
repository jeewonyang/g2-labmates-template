import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { listTasks, countTriageTasks, type TaskFilters } from "@/lib/services/tasks";
import { listProjects } from "@/lib/services/projects";
import { listAreas } from "@/lib/services/areas";
import { PageHeader, SectionCard, EmptyState } from "@/components/ui/primitives";
import { TaskList } from "@/components/tasks/TaskItem";
import { NewTaskButton } from "@/components/forms/CreateForms";
import { ClearCompletedButton } from "@/components/tasks/ClearCompletedButton";
import { cn } from "@/lib/utils";
import {
  PRIORITIES,
  PRIORITY_META,
  TASK_CONTEXTS,
  TASK_CONTEXT_META,
} from "@/lib/types";

export const dynamic = "force-dynamic";

const VIEWS = [
  { key: "today", label: "Today" },
  { key: "triage", label: "Needs triage" },
  { key: "upcoming", label: "Upcoming" },
  { key: "waiting", label: "Waiting" },
  { key: "someday", label: "Someday" },
  { key: "all", label: "All open" },
  { key: "completed", label: "Completed" },
] as const;

export default async function TasksPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const requestedView = sp.view === "inbox" ? "triage" : sp.view;
  const view = (
    VIEWS.some((candidate) => candidate.key === requestedView)
      ? requestedView
      : "today"
  ) as NonNullable<TaskFilters["view"]>;
  const filters: TaskFilters = {
    view,
    priority: sp.priority,
    context: sp.context,
    projectId: sp.project,
    areaId: sp.area,
  };

  const [tasks, projects, areas, triageCount] = await Promise.all([
    listTasks(filters),
    listProjects(),
    listAreas(),
    countTriageTasks(),
  ]);
  const projectOptions = projects.map((p) => ({
    id: p.id,
    title: p.title,
    areaId: p.areaId,
  }));
  const areaOptions = areas.map((a) => ({ id: a.id, title: a.title }));

  const buildHref = (patch: Record<string, string | undefined>) => {
    const params = new URLSearchParams();
    const merged = { view, priority: sp.priority, context: sp.context, ...patch };
    for (const [k, v] of Object.entries(merged)) if (v) params.set(k, v);
    return `/tasks?${params.toString()}`;
  };

  return (
    <div>
      <PlannerNav />
      <PageHeader
        title="Tasks"
        subtitle="Every active task gets a due date or action date; Waiting and Someday are exempt."
        actions={<NewTaskButton projects={projectOptions} areas={areaOptions} openOnMount={sp.new === "1"} />}
      />

      {/* View tabs */}
      <div className="mb-4 flex flex-wrap gap-1 border-b pb-2">
        {VIEWS.map((v) => (
          <Link
            key={v.key}
            href={buildHref({ view: v.key })}
            className={cn(
              "flex items-center gap-1.5 rounded-[var(--radius-sm)] px-3 py-1.5 text-sm font-medium transition-colors",
              view === v.key
                ? "bg-[var(--accent-soft)] text-[var(--accent-ink)]"
                : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
            )}
          >
            {v.label}
            {v.key === "triage" && triageCount > 0 && (
              <span className="rounded-full bg-[var(--amber-soft)] px-1.5 text-xs font-semibold text-[var(--amber)]">
                {triageCount}
              </span>
            )}
          </Link>
        ))}
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-[var(--ink-3)]">Priority:</span>
        <FilterChip href={buildHref({ priority: undefined })} active={!sp.priority} label="Any" />
        {PRIORITIES.map((p) => (
          <FilterChip key={p} href={buildHref({ priority: p })} active={sp.priority === p} label={PRIORITY_META[p].label} />
        ))}
        <span className="ml-3 text-[var(--ink-3)]">Context:</span>
        <FilterChip href={buildHref({ context: undefined })} active={!sp.context} label="Any" />
        {TASK_CONTEXTS.slice(0, 6).map((c) => (
          <FilterChip key={c} href={buildHref({ context: c })} active={sp.context === c} label={TASK_CONTEXT_META[c].label} />
        ))}
      </div>

      <SectionCard
        title={`${VIEWS.find((v) => v.key === view)?.label ?? "Tasks"} · ${tasks.length}`}
        action={
          view === "completed" ? <ClearCompletedButton count={tasks.length} /> : undefined
        }
      >
        {view === "triage" && tasks.length > 0 && (
          <p className="mb-3 text-xs text-[var(--ink-3)]">
            These active tasks have neither a due date nor an action date. Open each task to set one,
            or move it to Waiting or Someday when a date is intentionally unknown.
          </p>
        )}
        {tasks.length ? (
          <TaskList
            tasks={tasks}
            showHighlight={view !== "completed"}
            flagMissing={view === "triage"}
          />
        ) : view === "triage" ? (
          <EmptyState
            title="Nothing to triage"
            description="Every active task has a due date or action date."
          />
        ) : (
          <EmptyState title="No tasks here" description="Adjust filters, switch lists, or capture something new." />
        )}
      </SectionCard>
    </div>
  );
}

function FilterChip({ href, active, label }: { href: string; active: boolean; label: string }) {
  return (
    <Link
      href={href}
      className={cn(
        "rounded-full border px-2.5 py-1 font-medium transition-colors",
        active
          ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent-ink)]"
          : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
      )}
    >
      {label}
    </Link>
  );
}
