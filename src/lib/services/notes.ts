import { endOfDay, startOfDay } from "date-fns";
import { db } from "@/lib/db";
import type { z } from "zod";
import type { noteInputSchema } from "@/lib/validators";

type NoteInput = z.infer<typeof noteInputSchema>;

const noteInclude = {
  project: { select: { id: true, title: true } },
  area: { select: { id: true, title: true } },
  tags: true,
} as const;

export async function listNotes(filters: { type?: string; tag?: string; q?: string } = {}) {
  return db.note.findMany({
    where: {
      archivedAt: null,
      ...(filters.type ? { type: filters.type } : {}),
      ...(filters.tag ? { tags: { some: { name: filters.tag } } } : {}),
      ...(filters.q
        ? {
            OR: [
              { title: { contains: filters.q } },
              { contentMarkdown: { contains: filters.q } },
            ],
          }
        : {}),
    },
    orderBy: [{ pinned: "desc" }, { updatedAt: "desc" }],
    include: noteInclude,
    take: 200,
  });
}

export async function getNote(id: string) {
  return db.note.findUnique({
    where: { id },
    include: {
      ...noteInclude,
      resource: { select: { id: true, title: true } },
      tasks: { select: { id: true, title: true, status: true } },
      linkedNotes: { select: { id: true, title: true, type: true } },
      linkedFrom: { select: { id: true, title: true, type: true } },
    },
  });
}

export async function createNote(input: NoteInput) {
  const { tags, ...data } = input;
  return db.note.create({
    data: {
      ...data,
      contentMarkdown: data.contentMarkdown ?? "",
      tags: tags?.length
        ? { connectOrCreate: tags.map((name) => ({ where: { name }, create: { name } })) }
        : undefined,
    },
  });
}

export async function updateNote(id: string, input: Partial<NoteInput>) {
  const { tags, ...data } = input;
  return db.note.update({
    where: { id },
    data: {
      ...data,
      tags: tags
        ? { set: [], connectOrCreate: tags.map((name) => ({ where: { name }, create: { name } })) }
        : undefined,
    },
  });
}

export async function linkNotes(fromId: string, toId: string) {
  return db.note.update({
    where: { id: fromId },
    data: { linkedNotes: { connect: { id: toId } } },
  });
}

export async function deleteNote(id: string) {
  return archiveNote(id);
}

export async function archiveNote(id: string) {
  return db.note.update({ where: { id }, data: { archivedAt: new Date() } });
}

export async function togglePinNote(id: string) {
  const note = await db.note.findUniqueOrThrow({ where: { id } });
  return db.note.update({ where: { id }, data: { pinned: !note.pinned } });
}

export async function getPinnedNotes() {
  return db.note.findMany({
    where: { pinned: true, archivedAt: null },
    orderBy: { updatedAt: "desc" },
    include: noteInclude,
  });
}

/** The journal note for a given day (used by Today's daily-note panel). */
export async function getDailyNote(date = new Date()) {
  return db.note.findFirst({
    where: {
      type: "journal",
      date: { gte: startOfDay(date), lte: endOfDay(date) },
      archivedAt: null,
    },
  });
}

export async function upsertDailyNote(content: string, date = new Date()) {
  const existing = await getDailyNote(date);
  if (existing) {
    return db.note.update({
      where: { id: existing.id },
      data: { contentMarkdown: content },
    });
  }
  return db.note.create({
    data: {
      title: `Journal — ${date.toISOString().slice(0, 10)}`,
      contentMarkdown: content,
      type: "journal",
      date: startOfDay(date),
    },
  });
}
