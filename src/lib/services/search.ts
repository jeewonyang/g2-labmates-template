import { db } from "@/lib/db";

export type SearchResult = {
  id: string;
  entity: "project" | "task" | "note" | "resource" | "goal" | "area";
  title: string;
  subtitle?: string | null;
  href: string;
};

/**
 * Global substring search across all major entities. Powers the command
 * palette. SQLite `contains` is case-insensitive for ASCII; good enough
 * until a real FTS index is warranted.
 */
export async function globalSearch(q: string, limit = 8): Promise<SearchResult[]> {
  const query = q.trim();
  if (!query) return [];

  const [projects, tasks, notes, resources, goals, areas] = await Promise.all([
    db.project.findMany({
      where: { title: { contains: query }, archivedAt: null },
      take: limit,
      select: { id: true, title: true, status: true },
    }),
    db.task.findMany({
      where: { title: { contains: query }, archivedAt: null },
      take: limit,
      select: { id: true, title: true, status: true, project: { select: { title: true } } },
    }),
    db.note.findMany({
      where: {
        archivedAt: null,
        OR: [{ title: { contains: query } }, { contentMarkdown: { contains: query } }],
      },
      take: limit,
      select: { id: true, title: true, type: true },
    }),
    db.resource.findMany({
      where: {
        archivedAt: null,
        OR: [{ title: { contains: query } }, { summary: { contains: query } }],
      },
      take: limit,
      select: { id: true, title: true, type: true },
    }),
    db.goal.findMany({
      where: { title: { contains: query }, archivedAt: null },
      take: limit,
      select: { id: true, title: true, year: true },
    }),
    db.area.findMany({
      where: { title: { contains: query }, archivedAt: null },
      take: limit,
      select: { id: true, title: true, type: true },
    }),
  ]);

  return [
    ...projects.map((p): SearchResult => ({
      id: p.id, entity: "project", title: p.title, subtitle: p.status, href: `/projects/${p.id}`,
    })),
    ...tasks.map((t): SearchResult => ({
      id: t.id, entity: "task", title: t.title, subtitle: t.project?.title ?? t.status, href: `/tasks?highlight=${t.id}`,
    })),
    ...notes.map((n): SearchResult => ({
      id: n.id, entity: "note", title: n.title, subtitle: n.type, href: `/notes/${n.id}`,
    })),
    ...resources.map((r): SearchResult => ({
      id: r.id, entity: "resource", title: r.title, subtitle: r.type, href: `/resources/${r.id}`,
    })),
    ...goals.map((g): SearchResult => ({
      id: g.id, entity: "goal", title: g.title, subtitle: g.year ? String(g.year) : null, href: `/goals/${g.id}`,
    })),
    ...areas.map((a): SearchResult => ({
      id: a.id, entity: "area", title: a.title, subtitle: a.type, href: `/areas/${a.id}`,
    })),
  ].slice(0, limit * 3);
}
