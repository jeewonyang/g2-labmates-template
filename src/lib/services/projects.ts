import { db } from "@/lib/db";
import type { z } from "zod";
import type { projectInputSchema } from "@/lib/validators";

type ProjectInput = z.infer<typeof projectInputSchema>;

/** Progress = fraction of this project's tasks completed. */
export function computeProgress(tasks: { status: string }[]): number | null {
  const relevant = tasks.filter((t) => t.status !== "canceled");
  if (relevant.length === 0) return null;
  const done = relevant.filter((t) => t.status === "completed").length;
  return done / relevant.length;
}

const projectListInclude = {
  area: { select: { id: true, title: true } },
  goal: { select: { id: true, title: true } },
  nextAction: { select: { id: true, title: true, status: true } },
  tasks: { select: { status: true } },
} as const;

export type ProjectWithProgress = Awaited<ReturnType<typeof listProjects>>[number];

export async function listProjects(opts: { includeArchived?: boolean } = {}) {
  const projects = await db.project.findMany({
    where: opts.includeArchived ? {} : { archivedAt: null, status: { not: "archived" } },
    orderBy: [{ targetDate: "asc" }, { updatedAt: "desc" }],
    include: projectListInclude,
  });
  return projects.map((p) => ({ ...p, progress: computeProgress(p.tasks) }));
}

export async function getProject(id: string) {
  const project = await db.project.findUnique({
    where: { id },
    include: {
      area: { select: { id: true, title: true } },
      goal: { select: { id: true, title: true } },
      nextAction: true,
      tasks: {
        where: { archivedAt: null },
        orderBy: [{ status: "asc" }, { dueDate: "asc" }, { createdAt: "desc" }],
        include: { tags: true },
      },
      notes: { where: { archivedAt: null }, orderBy: { updatedAt: "desc" } },
      resources: { where: { archivedAt: null }, orderBy: { updatedAt: "desc" } },
      tags: true,
    },
  });
  if (!project) return null;
  return { ...project, progress: computeProgress(project.tasks) };
}

export async function createProject(input: ProjectInput) {
  return db.project.create({ data: input });
}

export async function updateProject(id: string, input: Partial<ProjectInput>) {
  if (input.areaId === undefined) {
    return db.project.update({ where: { id }, data: input });
  }
  return db.$transaction(async (tx) => {
    const project = await tx.project.update({ where: { id }, data: input });
    await tx.task.updateMany({
      where: { projectId: id, archivedAt: null },
      data: { areaId: input.areaId },
    });
    return project;
  });
}

export async function setProjectStatus(id: string, status: string) {
  return db.project.update({
    where: { id },
    data: {
      status,
      completedAt: status === "completed" ? new Date() : null,
      archivedAt: status === "archived" ? new Date() : null,
    },
  });
}

export async function setNextAction(projectId: string, taskId: string | null) {
  if (taskId) {
    const task = await db.task.findFirst({
      where: {
        id: taskId,
        projectId,
        archivedAt: null,
        status: { notIn: ["completed", "canceled"] },
      },
      select: { id: true },
    });
    if (!task) {
      throw new Error("Next action must be an open task in this project.");
    }
  }
  return db.project.update({
    where: { id: projectId },
    data: { nextActionId: taskId },
  });
}

/**
 * Active projects with no open next action or no activity recently —
 * surfaced on Today as "needs attention".
 */
/** Soft delete: the project leaves the active lists but stays on /archive. */
export async function archiveProject(id: string) {
  return db.project.update({
    where: { id },
    data: { archivedAt: new Date(), status: "archived" },
  });
}

export async function getProjectsNeedingAttention() {
  const projects = await db.project.findMany({
    where: { status: "active", archivedAt: null },
    include: projectListInclude,
  });
  return projects
    .map((p) => ({ ...p, progress: computeProgress(p.tasks) }))
    .filter(
      (p) =>
        !p.nextAction ||
        p.nextAction.status === "completed" ||
        p.nextAction.status === "canceled"
    );
}

export async function getActiveProjects() {
  const projects = await db.project.findMany({
    where: { status: "active", archivedAt: null },
    orderBy: [{ targetDate: "asc" }, { updatedAt: "desc" }],
    include: projectListInclude,
  });
  return projects.map((p) => ({ ...p, progress: computeProgress(p.tasks) }));
}

export async function getCompletedProjectsInRange(from: Date, to: Date) {
  return db.project.findMany({
    where: { status: "completed", completedAt: { gte: from, lte: to } },
    orderBy: { completedAt: "desc" },
  });
}
