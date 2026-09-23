import { db } from "@/lib/db";
import { deriveTitle } from "@/lib/utils";
import type { CaptureInput } from "@/lib/validators";
import { Prisma } from "@prisma/client";
import { queueCaptureAutomation } from "@/lib/services/automation";

/**
 * Capture service — the single entry point for creating inbox items,
 * shared by the web quick-capture UI (via server action) and the REST
 * capture API (used later by iOS app/widget/share-sheet/Siri clients).
 *
 * Guarantees:
 * - Idempotent when the client supplies `clientId` (safe offline retries).
 * - Never rejects a valid capture because optional context is missing.
 */

export async function createInboxItem(input: CaptureInput) {
  // Idempotency: if this clientId was already synced, return the original.
  if (input.clientId) {
    const existing = await db.inboxItem.findUnique({
      where: { clientId: input.clientId },
      include: { automation: true },
    });
    if (existing) return { item: existing, deduplicated: true as const };
  }

  let created;
  try {
    created = await db.inboxItem.create({
      data: {
        rawText: input.rawText,
        type: input.type ?? "unknown",
        parsedTitle: input.parsedTitle ?? deriveTitle(input.rawText),
        source: input.source ?? "api",
        sourceUrl: input.sourceUrl,
        dueDate: input.dueDate,
        metadata: input.metadata ? JSON.stringify(input.metadata) : null,
        clientId: input.clientId,
        capturedAt: input.capturedAt ?? new Date(),
        projectId: input.projectId,
        areaId: input.areaId,
        tags: input.tags?.length
          ? {
              connectOrCreate: input.tags.map((name) => ({
                where: { name },
                create: { name },
              })),
            }
          : undefined,
        automation: {
          create: {
            mode: input.automationMode,
            state: input.automationMode === "automatic" ? "queued" : "overridden",
            completedAt: input.automationMode === "manual" ? new Date() : undefined,
            events: {
              create: {
                type: "captured",
                actor: input.source ?? "api",
                payload: JSON.stringify({ mode: input.automationMode }),
              },
            },
          },
        },
      },
      include: { automation: true },
    });
  } catch (error) {
    // The optimistic lookup above is not enough under concurrent offline
    // retries. The unique clientId constraint is the arbiter; a losing request
    // returns the winner instead of surfacing P2002.
    if (
      input.clientId &&
      error instanceof Prisma.PrismaClientKnownRequestError &&
      error.code === "P2002"
    ) {
      const existing = await db.inboxItem.findUnique({
        where: { clientId: input.clientId },
        include: { automation: true },
      });
      if (existing) return { item: existing, deduplicated: true as const };
    }
    throw error;
  }

  if (input.automationMode === "automatic") {
    // Capture durability comes first. If the local model or ledger is
    // unavailable, queueCaptureAutomation records a retryable failed state and
    // the API still returns the safely persisted inbox item.
    await queueCaptureAutomation(created.id).catch(() => undefined);
    created = await db.inboxItem.findUniqueOrThrow({
      where: { id: created.id },
      include: { automation: true },
    });
  }
  return { item: created, deduplicated: false as const };
}

export async function createInboxItemsBatch(inputs: CaptureInput[]) {
  const results = [];
  for (const input of inputs) {
    results.push(await createInboxItem(input));
  }
  return results;
}

export async function listInboxItems(status: string = "inbox") {
  return db.inboxItem.findMany({
    where: { status },
    orderBy: { capturedAt: "desc" },
    include: { tags: true, project: true, area: true, automation: true },
  });
}

export async function countInbox() {
  return db.inboxItem.count({ where: { status: "inbox" } });
}

/**
 * Triage: convert an inbox item into a real Task/Note/Resource, carrying
 * over tags, links, and dates, then mark the item processed.
 */
export async function processInboxItem(
  id: string,
  into: "task" | "note" | "resource",
  overrides?: { title?: string; projectId?: string | null; areaId?: string | null }
) {
  return db.$transaction(async (tx) => {
    // Claim the item inside the same transaction as entity creation. This
    // prevents double-clicks and the automatic worker from both materializing
    // the same capture.
    const claimed = await tx.inboxItem.updateMany({
      where: { id, status: "inbox" },
      data: { status: "processing" },
    });
    if (claimed.count !== 1) {
      const existing = await tx.inboxItem.findUniqueOrThrow({ where: { id } });
      if (existing.status === "processed" && existing.processedIntoId) {
        return {
          into: (existing.processedIntoType ?? into) as "task" | "note" | "resource",
          createdId: existing.processedIntoId,
          deduplicated: true,
        };
      }
      throw new Error(`Inbox item is already ${existing.status}.`);
    }

    const item = await tx.inboxItem.findUniqueOrThrow({
      where: { id },
      include: { tags: true, automation: true },
    });
    const title =
      overrides?.title?.trim() || item.parsedTitle || deriveTitle(item.rawText);
    const projectId =
      overrides?.projectId !== undefined ? overrides.projectId : item.projectId;
    const areaId = overrides?.areaId !== undefined ? overrides.areaId : item.areaId;
    const tagConnect = item.tags.length
      ? { connect: item.tags.map((tag) => ({ id: tag.id })) }
      : undefined;

    let createdId: string;
    if (into === "task") {
      createdId = (
        await tx.task.create({
          data: {
            title,
            description: item.rawText !== title ? item.rawText : undefined,
            status: item.dueDate ? "scheduled" : "next",
            dueDate: item.dueDate,
            projectId,
            areaId,
            tags: tagConnect,
          },
        })
      ).id;
    } else if (into === "note") {
      createdId = (
        await tx.note.create({
          data: {
            title,
            contentMarkdown: item.rawText,
            type: item.type === "journal" ? "journal" : "fleeting",
            sourceUrl: item.sourceUrl,
            projectId,
            areaId,
            tags: tagConnect,
          },
        })
      ).id;
    } else {
      createdId = (
        await tx.resource.create({
          data: {
            title,
            url: item.sourceUrl,
            summary: item.rawText !== title ? item.rawText : undefined,
            status: "inbox",
            projectId,
            areaId,
            tags: tagConnect,
          },
        })
      ).id;
    }

    await tx.inboxItem.update({
      where: { id },
      data: {
        status: "processed",
        processedIntoType: into,
        processedIntoId: createdId,
      },
    });
    if (item.automation && item.automation.state !== "applied") {
      await tx.captureAutomation.update({
        where: { id: item.automation.id },
        data: {
          mode: "manual",
          state: "overridden",
          completedAt: new Date(),
          events: {
            create: {
              type: "manual_override",
              actor: "owner",
              payload: JSON.stringify({ into, createdId }),
            },
          },
        },
      });
    }
    return { into, createdId, deduplicated: false };
  });
}

export async function archiveInboxItem(id: string) {
  return db.$transaction(async (tx) => {
    const item = await tx.inboxItem.update({
      where: { id },
      data: { status: "archived" },
      include: { automation: true },
    });
    if (item.automation && item.automation.state !== "applied") {
      await tx.captureAutomation.update({
        where: { id: item.automation.id },
        data: {
          mode: "manual",
          state: "overridden",
          completedAt: new Date(),
          events: {
            create: {
              type: "manual_archive",
              actor: "owner",
            },
          },
        },
      });
    }
    return item;
  });
}
