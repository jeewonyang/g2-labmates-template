import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { db } from "@/lib/db";
import { PageHeader, SectionCard, EmptyState } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/Badge";

export const dynamic = "force-dynamic";

export default async function ArchivePage() {
  // Archived inbox items were fetched for years and never rendered — the dead
  // read was dropped 2026-08-27; captures keep their history in /inbox's
  // "Recently organized" and the automation ledger.
  const [projects, tasks, notes, resources] = await Promise.all([
    db.project.findMany({
      where: { OR: [{ archivedAt: { not: null } }, { status: "archived" }] },
      orderBy: { updatedAt: "desc" },
      take: 50,
    }),
    db.task.findMany({ where: { archivedAt: { not: null } }, orderBy: { updatedAt: "desc" }, take: 50 }),
    db.note.findMany({ where: { archivedAt: { not: null } }, orderBy: { updatedAt: "desc" }, take: 50 }),
    db.resource.findMany({ where: { archivedAt: { not: null } }, orderBy: { updatedAt: "desc" }, take: 50 }),
  ]);

  const total = projects.length + tasks.length + notes.length + resources.length;

  return (
    <div>
      <PlannerNav />
      <PageHeader title="Archive" subtitle="Completed and inactive items, kept for reference." />

      {total === 0 ? (
        <EmptyState title="Archive is empty" description="Archived projects, tasks, notes, and captures will collect here." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <SectionCard title={`Projects · ${projects.length}`}>
            {projects.length ? (
              <ul className="divide-y">
                {projects.map((p) => (
                  <li key={p.id}>
                    <Link href={`/projects/${p.id}`} className="flex items-center justify-between gap-2 py-2 hover:opacity-80">
                      <span className="truncate text-sm text-[var(--ink-2)]">{p.title}</span>
                      <Badge tone="gray">{p.status}</Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : <Empty />}
          </SectionCard>

          <SectionCard title={`Notes · ${notes.length}`}>
            {notes.length ? (
              <ul className="divide-y">
                {notes.map((n) => (
                  <li key={n.id}>
                    <Link href={`/notes/${n.id}`} className="block truncate py-2 text-sm text-[var(--ink-2)] hover:opacity-80">{n.title}</Link>
                  </li>
                ))}
              </ul>
            ) : <Empty />}
          </SectionCard>

          <SectionCard title={`Resources · ${resources.length}`}>
            {resources.length ? (
              <ul className="divide-y">
                {resources.map((r) => (
                  <li key={r.id}>
                    <Link href={`/resources/${r.id}`} className="block truncate py-2 text-sm text-[var(--ink-2)] hover:opacity-80">{r.title}</Link>
                  </li>
                ))}
              </ul>
            ) : <Empty />}
          </SectionCard>

          <SectionCard title={`Tasks · ${tasks.length}`}>
            {tasks.length ? (
              <ul className="divide-y">
                {tasks.map((t) => (
                  <li key={t.id} className="truncate py-2 text-sm text-[var(--ink-2)]">{t.title}</li>
                ))}
              </ul>
            ) : <Empty />}
          </SectionCard>
        </div>
      )}
    </div>
  );
}

function Empty() {
  return <p className="text-sm text-[var(--ink-3)]">Nothing archived.</p>;
}
