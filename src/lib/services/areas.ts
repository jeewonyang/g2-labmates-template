import { db } from "@/lib/db";
import { computeProgress } from "@/lib/services/projects";

export async function listAreas(opts: { type?: string; includeArchived?: boolean } = {}) {
  return db.area.findMany({
    where: {
      ...(opts.type ? { type: opts.type } : {}),
      ...(opts.includeArchived ? {} : { archivedAt: null }),
    },
    orderBy: [{ pinned: "desc" }, { title: "asc" }],
    include: {
      _count: {
        select: {
          projects: { where: { status: "active", archivedAt: null } },
          tasks: { where: { status: { notIn: ["completed", "canceled"] }, archivedAt: null } },
          notes: { where: { archivedAt: null } },
          resources: { where: { archivedAt: null } },
        },
      },
    },
  });
}

export async function getArea(id: string) {
  const area = await db.area.findUnique({
    where: { id },
    include: {
      projects: {
        where: { archivedAt: null },
        orderBy: { updatedAt: "desc" },
        include: { tasks: { select: { status: true } } },
      },
      tasks: {
        where: { status: { notIn: ["completed", "canceled"] }, archivedAt: null },
        orderBy: [{ dueDate: "asc" }, { createdAt: "desc" }],
        include: { project: { select: { id: true, title: true } }, tags: true },
      },
      notes: { where: { archivedAt: null }, orderBy: { updatedAt: "desc" }, take: 20 },
      resources: { where: { archivedAt: null }, orderBy: { updatedAt: "desc" }, take: 20 },
      goals: { where: { archivedAt: null }, orderBy: { targetDate: "asc" } },
    },
  });
  if (!area) return null;
  return {
    ...area,
    projects: area.projects.map((p) => ({ ...p, progress: computeProgress(p.tasks) })),
  };
}

export async function createArea(input: {
  title: string;
  description?: string;
  type?: string;
  icon?: string;
}) {
  return db.area.create({ data: input });
}

export async function updateArea(
  id: string,
  input: Partial<{ title: string; description: string; type: string; health: string; pinned: boolean }>
) {
  return db.area.update({ where: { id }, data: input });
}

export async function archiveArea(id: string) {
  return db.area.update({ where: { id }, data: { archivedAt: new Date() } });
}
