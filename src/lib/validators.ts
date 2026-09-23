import { z } from "zod";
import {
  CAPTURE_SOURCES,
  INBOX_ITEM_TYPES,
  NOTE_TYPES,
  PRIORITIES,
  PROJECT_STATUSES,
  RESOURCE_STATUSES,
  RESOURCE_TYPES,
  REVIEW_TYPES,
  TASK_STATUSES,
} from "@/lib/types";

/**
 * Date field that treats a date-only string ("2026-07-07") as LOCAL midnight.
 * Plain z.coerce.date() runs new Date(string), which parses date-only strings
 * as UTC midnight — 4-5pm the *previous* day in Pacific time, so a task due
 * "today" rendered as overdue. Datetime strings without a zone
 * ("2026-07-07T14:30") already parse as local time per the ES spec.
 */
const localDate = z.preprocess((v) => {
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v.trim())) {
    const [y, m, d] = v.trim().split("-").map(Number);
    return new Date(y, m - 1, d);
  }
  return v;
}, z.coerce.date());

/**
 * Payload accepted by POST /api/capture and the web quick-capture form.
 * Every field except rawText is optional so the dumbest possible client
 * (a Siri shortcut posting one string) still works.
 */
export const captureInputSchema = z.object({
  rawText: z.string().trim().min(1, "rawText is required").max(20_000),
  type: z.enum(INBOX_ITEM_TYPES).optional().default("unknown"),
  parsedTitle: z.string().trim().max(300).optional(),
  source: z.enum(CAPTURE_SOURCES).optional().default("api"),
  sourceUrl: z.string().url().max(2000).optional(),
  dueDate: localDate.optional(),
  tags: z.array(z.string().trim().min(1).max(60)).max(20).optional(),
  projectId: z.string().optional(),
  areaId: z.string().optional(),
  metadata: z.record(z.unknown()).optional(),
  // Automatic is the default: the capture is staged in the private inbox,
  // classified locally, independently verified, and then applied according to
  // policy. Manual keeps the item in the dashboard inbox for direct triage.
  automationMode: z.enum(["automatic", "manual"]).optional().default("automatic"),
  // Client-generated idempotency key. Offline clients set this so retried
  // syncs never create duplicates.
  clientId: z.string().trim().min(8).max(128).optional(),
  // Client-side capture timestamp (may predate server receipt when offline).
  capturedAt: z.coerce.date().optional(),
});

export type CaptureInput = z.infer<typeof captureInputSchema>;

/** Batch shape for offline sync: POST /api/capture/batch */
export const captureBatchSchema = z.object({
  items: z.array(captureInputSchema).min(1).max(100),
});

/**
 * Deliberately tiny browser contract for an implementation run. The server
 * fixes the repo, executable, sandbox, tools, model, and environment.
 */
export const g2AgentRunSchema = z.object({
  clientRequestId: z.string().uuid(),
  prompt: z.string().trim().min(3, "prompt is required").max(8_000),
  provider: z.enum(["codex", "claude"]),
}).strict();

export const researchReviewRequestSchema = z.object({
  clientRequestId: z.string().uuid(),
  source: z.enum(["doi", "feed"]),
  targetType: z.enum(["project", "resource"]).optional(),
  targetId: z.string().trim().min(1).max(200).optional(),
  doi: z.string().trim().max(500).optional(),
  feedKey: z.string().trim().min(1).max(100).optional(),
  sourceRef: z.string().trim().min(1).max(2_000).optional(),
}).strict().superRefine((value, context) => {
  if (Boolean(value.targetType) !== Boolean(value.targetId)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["targetId"],
      message: "Choose both a destination type and item, or neither.",
    });
  }
  if (value.source === "doi" && !value.doi) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["doi"],
      message: "DOI is required.",
    });
  }
  if (value.source === "feed" && (!value.feedKey || !value.sourceRef)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["sourceRef"],
      message: "Feed source is required.",
    });
  }
});

export const researchBibliographyItemIdSchema = z.string()
  .trim()
  .min(1)
  .max(200)
  .regex(/^[a-z0-9_-]+$/i);

/**
 * Filing a report the CEO Brief rendered. The path is vault-relative and the
 * service reads it through readVaultFile, which is scoped to VAULT/Memory - so
 * this only has to reject the obvious, not carry the security guarantee.
 */
export const researchDigestSaveSchema = z.object({
  digestPath: z.string().trim().min(1).max(400)
    .regex(/\.md$/i, "A markdown report path is required.")
    .refine(
      (value) => {
        const parts = value.replace(/\\/g, "/").split("/");
        return !parts.includes("..") && !parts.includes(".") && !/^[a-z]:/i.test(value);
      },
      { message: "A vault-relative report path is required." },
    ),
  targetType: z.enum(["project", "resource", "area"]).optional(),
  targetId: z.string().trim().min(1).max(200).optional(),
}).strict().superRefine((value, context) => {
  if (Boolean(value.targetType) !== Boolean(value.targetId)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["targetId"],
      message: "Choose both a destination type and item, or neither.",
    });
  }
});

export const researchBibliographyReclassifySchema = z.object({
  itemId: researchBibliographyItemIdSchema,
  targetType: z.enum(["project", "resource", "area"]).optional(),
  targetId: z.string().trim().min(1).max(200).optional(),
}).strict().superRefine((value, context) => {
  if (Boolean(value.targetType) !== Boolean(value.targetId)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["targetId"],
      message: "Choose both a destination type and item, or neither.",
    });
  }
});

export const taskInputSchema = z.object({
  title: z.string().trim().min(1).max(300),
  description: z.string().max(10_000).optional(),
  status: z.enum(TASK_STATUSES).optional(),
  priority: z.enum(PRIORITIES).optional(),
  context: z.string().max(60).optional(),
  isHighlight: z.boolean().optional(),
  dueDate: localDate.nullable().optional(),
  scheduledDate: localDate.nullable().optional(),
  projectId: z.string().nullable().optional(),
  areaId: z.string().nullable().optional(),
  tags: z.array(z.string().trim().min(1).max(60)).optional(),
});

/** Narrow payload for moving a dated task between calendar days. */
export const taskCalendarMoveSchema = z.object({
  targetDate: localDate,
}).strict();

/**
 * A stretch of time on the Actual side of the Plan & actual board. Times arrive
 * as ISO strings from the browser and are coerced; the day column is derived
 * server-side from startAt, never sent. `strict()` so the client cannot smuggle
 * a field the dialog does not show.
 */
/** A task dropped onto the Plan column at a time. */
export const taskPlacementSchema = z
  .object({ taskId: z.string().trim().min(1).max(64), startAt: z.coerce.date() })
  .strict();

export const TIME_ENTRY_KINDS = ["task", "block", "other"] as const;
export const timeEntryInputSchema = z
  .object({
    startAt: z.coerce.date(),
    endAt: z.coerce.date(),
    title: z.string().trim().min(1).max(200),
    kind: z.enum(TIME_ENTRY_KINDS).default("other"),
    taskId: z.string().trim().min(1).max(64).nullable().optional(),
    blockId: z.string().trim().min(1).max(64).nullable().optional(),
    note: z.string().trim().max(1000).nullable().optional(),
  })
  .strict()
  .refine((v) => v.endAt.getTime() - v.startAt.getTime() >= 5 * 60_000, {
    message: "An entry must be at least five minutes long",
    path: ["endAt"],
  });

export const noteInputSchema = z.object({
  title: z.string().trim().min(1).max(300),
  contentMarkdown: z.string().max(200_000).optional(),
  type: z.enum(NOTE_TYPES).optional(),
  sourceUrl: z.string().url().max(2000).nullable().optional(),
  date: localDate.nullable().optional(),
  pinned: z.boolean().optional(),
  projectId: z.string().nullable().optional(),
  areaId: z.string().nullable().optional(),
  resourceId: z.string().nullable().optional(),
  tags: z.array(z.string().trim().min(1).max(60)).optional(),
});

export const resourceInputSchema = z.object({
  title: z.string().trim().min(1).max(300),
  type: z.enum(RESOURCE_TYPES).optional(),
  url: z.string().url().max(2000).nullable().optional(),
  summary: z.string().max(20_000).optional(),
  status: z.enum(RESOURCE_STATUSES).optional(),
  projectId: z.string().nullable().optional(),
  areaId: z.string().nullable().optional(),
  tags: z.array(z.string().trim().min(1).max(60)).optional(),
});

export const projectStatusSchema = z.enum(PROJECT_STATUSES);

export const projectInputSchema = z.object({
  title: z.string().trim().min(1).max(300),
  description: z.string().max(20_000).optional(),
  status: z.enum(PROJECT_STATUSES).optional(),
  priority: z.enum(PRIORITIES).optional(),
  areaId: z.string().nullable().optional(),
  goalId: z.string().nullable().optional(),
  startDate: localDate.nullable().optional(),
  targetDate: localDate.nullable().optional(),
});

/**
 * Tasks accepted from the text-extraction preview. A strict subset of
 * `taskInputSchema`: the preview may set what it can infer (context, project,
 * dates, status) and nothing else, so a parser bug cannot reach fields like
 * `isHighlight` that the dialog never shows.
 */
export const proposedTasksSchema = z
  .array(
    taskInputSchema.pick({
      title: true,
      description: true,
      status: true,
      context: true,
      projectId: true,
      scheduledDate: true,
    }),
  )
  .max(100);

export const reviewInputSchema = z.object({
  type: z.enum(REVIEW_TYPES),
  date: localDate,
  wins: z.string().max(20_000).optional(),
  challenges: z.string().max(20_000).optional(),
  lessons: z.string().max(20_000).optional(),
  priorities: z.string().max(20_000).optional(),
  contentMarkdown: z.string().max(200_000).optional(),
});

// ---------- Agent model picker (/teams) ----------
const jobKindSchema = z.string().regex(/^[a-z0-9_]+\.[a-z0-9_]+$/, "Unknown job kind.");
export const agentModelSchema = z
  .object({
    kinds: z.union([z.literal("*"), z.array(jobKindSchema).min(1).max(50)]),
    runtime: z.enum(["claude", "codex", "ollama"]),
    model: z
      .string()
      .trim()
      .regex(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,60}$/, "That is not a model name.")
      .nullable(),
  })
  .strict();

// ---------- Lab notebook (Research desk, 2026-09-21) ----------
const LAB_PROJECT_CODE = z.string().trim().regex(/^[A-Za-z][A-Za-z0-9]{0,40}$/, "unknown project");
const DATA_PATH = z.string().trim().min(1).max(1_000);

export const labRunSchema = z.object({
  clientRequestId: z.string().uuid(),
  assay: z.enum(["flow", "ultrasound", "primer-design"]),
  projectCode: LAB_PROJECT_CODE,
  mode: z.enum(["agent", "pipeline"]),
  inputPath: DATA_PATH,
  dnaPaths: z.array(DATA_PATH).max(12).optional(),
  instructions: z.string().trim().max(8_000).default(""),
  name: z.string().trim().max(200).optional(),
  newProject: z.boolean().optional(),
  options: z.object({
    negativeControl: z.string().trim().max(200).optional(),
    highlight: z.string().trim().max(200).optional(),
    compare: z.array(z.string().trim().min(1).max(400)).max(20).optional(),
    reference: z.string().trim().max(200).optional(),
  }).strict().optional(),
}).strict();

// Every entry records where its data came from and where the results went
// (the owner, 2026-09-21) - both required here and again in lab_notebook.py.
const notebookFields = {
  name: z.string().trim().max(200).optional(),
  summary: z.string().trim().max(600).optional(),
  assay: z.enum(["flow", "ultrasound", "primer-design", "bench", "computational", "other"]),
  outcome: z.enum(["positive", "negative", "mixed", "inconclusive", "technical-failure", "pending"]),
  status: z.enum(["draft", "final"]).optional(),
  inputPath: DATA_PATH,
  resultPath: DATA_PATH,
  introduction: z.string().max(20_000).optional(),
  objective: z.string().max(20_000).optional(),
  materialsMethods: z.string().max(20_000).optional(),
  result: z.string().max(20_000).optional(),
  conclusion: z.string().max(20_000).optional(),
  nextSteps: z.array(z.string().trim().max(300)).max(20).optional(),
};

export const notebookEntryCreateSchema = z.object({
  projectCode: LAB_PROJECT_CODE,
  experimentId: z.string().trim().regex(/^([A-Za-z0-9][A-Za-z0-9-]{0,23})?$/, "letters, digits and '-' only").optional(),
  date: z.string().trim().regex(/^(\d{4}-\d{2}-\d{2})?$/).optional(),
  newProject: z.boolean().optional(),
  ...notebookFields,
}).strict();

export const notebookEntryUpdateSchema = z.object({
  projectCode: LAB_PROJECT_CODE,
  entryName: z.string().trim().max(80),
  ...notebookFields,
}).strict();
