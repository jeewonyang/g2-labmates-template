import { db } from "@/lib/db";
import { computeProgress } from "@/lib/services/projects";

/** Goal progress = mean progress of linked projects (completed project = 1). */
function goalProgress(
  projects: { status: string; tasks: { status: string }[] }[]
): number | null {
  if (projects.length === 0) return null;
  const values = projects.map((p) =>
    p.status === "completed" ? 1 : computeProgress(p.tasks) ?? 0
  );
  return values.reduce((a, b) => a + b, 0) / values.length;
}

export async function listGoals(opts: { year?: number; includeArchived?: boolean } = {}) {
  const goals = await db.goal.findMany({
    where: {
      ...(opts.year ? { year: opts.year } : {}),
      ...(opts.includeArchived ? {} : { archivedAt: null }),
    },
    orderBy: [{ year: "desc" }, { quarter: "asc" }, { targetDate: "asc" }],
    include: {
      area: { select: { id: true, title: true } },
      projects: {
        where: { archivedAt: null },
        include: { tasks: { select: { status: true } } },
      },
    },
  });
  return goals.map((g) => ({ ...g, progress: goalProgress(g.projects) }));
}

export async function getGoal(id: string) {
  const goal = await db.goal.findUnique({
    where: { id },
    include: {
      area: { select: { id: true, title: true } },
      projects: {
        where: { archivedAt: null },
        orderBy: { updatedAt: "desc" },
        include: {
          tasks: { select: { status: true } },
          nextAction: { select: { id: true, title: true } },
        },
      },
    },
  });
  if (!goal) return null;
  return {
    ...goal,
    progress: goalProgress(goal.projects),
    projects: goal.projects.map((p) => ({ ...p, progress: computeProgress(p.tasks) })),
  };
}

export async function createGoal(input: {
  title: string;
  description?: string;
  year?: number;
  quarter?: number;
  targetDate?: Date | null;
  areaId?: string | null;
}) {
  return db.goal.create({ data: input });
}

export async function updateGoal(
  id: string,
  input: Partial<{
    title: string;
    description: string;
    status: string;
    year: number | null;
    quarter: number | null;
    targetDate: Date | null;
    areaId: string | null;
  }>
) {
  return db.goal.update({ where: { id }, data: input });
}

export async function archiveGoal(id: string) {
  return db.goal.update({ where: { id }, data: { archivedAt: new Date() } });
}
