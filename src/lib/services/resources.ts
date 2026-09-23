import { db } from "@/lib/db";
import type { z } from "zod";
import type { resourceInputSchema } from "@/lib/validators";

type ResourceInput = z.infer<typeof resourceInputSchema>;

const resourceInclude = {
  project: { select: { id: true, title: true } },
  area: { select: { id: true, title: true } },
  tags: true,
  _count: { select: { notes: true } },
} as const;

export async function listResources(
  filters: { type?: string; status?: string; tag?: string; q?: string } = {}
) {
  return db.resource.findMany({
    where: {
      archivedAt: null,
      ...(filters.type ? { type: filters.type } : {}),
      ...(filters.status ? { status: filters.status } : {}),
      ...(filters.tag ? { tags: { some: { name: filters.tag } } } : {}),
      ...(filters.q
        ? {
            OR: [
              { title: { contains: filters.q } },
              { summary: { contains: filters.q } },
              { url: { contains: filters.q } },
            ],
          }
        : {}),
    },
    orderBy: { updatedAt: "desc" },
    include: resourceInclude,
    take: 200,
  });
}

export async function getResource(id: string) {
  return db.resource.findUnique({
    where: { id },
    include: {
      ...resourceInclude,
      notes: { where: { archivedAt: null }, orderBy: { updatedAt: "desc" } },
    },
  });
}

export async function createResource(input: ResourceInput) {
  const { tags, ...data } = input;
  return db.resource.create({
    data: {
      ...data,
      tags: tags?.length
        ? { connectOrCreate: tags.map((name) => ({ where: { name }, create: { name } })) }
        : undefined,
    },
  });
}

export async function updateResource(id: string, input: Partial<ResourceInput>) {
  const { tags, ...data } = input;
  return db.resource.update({
    where: { id },
    data: {
      ...data,
      tags: tags
        ? { set: [], connectOrCreate: tags.map((name) => ({ where: { name }, create: { name } })) }
        : undefined,
    },
  });
}

export async function archiveResource(id: string) {
  return db.resource.update({ where: { id }, data: { archivedAt: new Date() } });
}
