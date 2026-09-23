/**
 * Single source of truth for entity vocabularies (statuses, types, priorities,
 * contexts) and their display metadata. The database stores plain strings, so
 * renaming a label or adding a new option only requires editing this file.
 */

// ---------- Priority ----------
export const PRIORITIES = ["low", "medium", "high", "urgent"] as const;
export type Priority = (typeof PRIORITIES)[number];

export const PRIORITY_META: Record<Priority, { label: string; rank: number }> = {
  urgent: { label: "Urgent", rank: 0 },
  high: { label: "High", rank: 1 },
  medium: { label: "Medium", rank: 2 },
  low: { label: "Low", rank: 3 },
};

// ---------- Task ----------
// GTD clarify outcomes, mirroring the Notion 명료화 field.
export const TASK_STATUSES = [
  "inbox",
  "next",
  "scheduled",
  "waiting",
  "someday",
  "completed",
  "canceled",
] as const;
export type TaskStatus = (typeof TASK_STATUSES)[number];

export const TASK_STATUS_META: Record<TaskStatus, { label: string }> = {
  inbox: { label: "Inbox" },
  next: { label: "Next action" },
  scheduled: { label: "Scheduled" },
  waiting: { label: "Waiting" },
  someday: { label: "Someday" },
  completed: { label: "Completed" },
  canceled: { label: "Canceled" },
};

export const OPEN_TASK_STATUSES: TaskStatus[] = [
  "inbox",
  "next",
  "scheduled",
  "waiting",
  "someday",
];

// GTD contexts, mirroring the Notion 다음 행동 상황 field.
export const TASK_CONTEXTS = [
  "office",
  "lab",
  "cbic",
  "computer",
  "phone",
  "home",
  "errand",
  "anywhere",
  "creative",
  "routine",
] as const;
export type TaskContext = (typeof TASK_CONTEXTS)[number];

export const TASK_CONTEXT_META: Record<TaskContext, { label: string }> = {
  office: { label: "Office" },
  lab: { label: "Lab" },
  cbic: { label: "CBIC" },
  computer: { label: "Computer" },
  phone: { label: "Phone" },
  home: { label: "Home" },
  errand: { label: "Out & about" },
  anywhere: { label: "Anywhere" },
  creative: { label: "Deep / creative" },
  routine: { label: "Routine work" },
};

// ---------- Project ----------
export const PROJECT_STATUSES = [
  "inbox",
  "active",
  "paused",
  "completed",
  "archived",
] as const;
export type ProjectStatus = (typeof PROJECT_STATUSES)[number];

export const PROJECT_STATUS_META: Record<ProjectStatus, { label: string }> = {
  inbox: { label: "Inbox" },
  active: { label: "Active" },
  paused: { label: "Paused" },
  // Stored value stays "completed" (completedAt bookkeeping keys on it);
  // the owner's word for it is Done (2026-09-21).
  completed: { label: "Done" },
  archived: { label: "Archived" },
};

// ---------- Area ----------
export const AREA_TYPES = ["area", "resource"] as const;
export type AreaType = (typeof AREA_TYPES)[number];

export const AREA_HEALTH = ["healthy", "needs_attention", "at_risk"] as const;
export type AreaHealth = (typeof AREA_HEALTH)[number];

export const AREA_HEALTH_META: Record<AreaHealth, { label: string }> = {
  healthy: { label: "Healthy" },
  needs_attention: { label: "Needs attention" },
  at_risk: { label: "At risk" },
};

// ---------- Goal ----------
export const GOAL_STATUSES = [
  "not_started",
  "in_progress",
  "paused",
  "completed",
] as const;
export type GoalStatus = (typeof GOAL_STATUSES)[number];

export const GOAL_STATUS_META: Record<GoalStatus, { label: string }> = {
  not_started: { label: "Not started" },
  in_progress: { label: "In progress" },
  paused: { label: "Paused" },
  completed: { label: "Completed" },
};

// ---------- Note ----------
export const NOTE_TYPES = [
  "fleeting",
  "literature",
  "permanent",
  "meeting",
  "journal",
  "review",
  "reference",
  // A lab notebook entry's planner copy; the markdown under
  // VAULT/Research-Private/.../04_Notebook/ is canonical (lab_notebook.py).
  "experiment",
] as const;
export type NoteType = (typeof NOTE_TYPES)[number];

export const NOTE_TYPE_META: Record<NoteType, { label: string }> = {
  fleeting: { label: "Fleeting" },
  literature: { label: "Literature" },
  permanent: { label: "Permanent" },
  meeting: { label: "Meeting" },
  journal: { label: "Journal" },
  review: { label: "Review" },
  reference: { label: "Reference" },
  experiment: { label: "Experiment" },
};

// ---------- Resource ----------
export const RESOURCE_TYPES = [
  "article",
  "book",
  "video",
  "course",
  "podcast",
  "document",
  "tool",
  "other",
] as const;
export type ResourceType = (typeof RESOURCE_TYPES)[number];

export const RESOURCE_TYPE_META: Record<ResourceType, { label: string }> = {
  article: { label: "Article" },
  book: { label: "Book" },
  video: { label: "Video" },
  course: { label: "Course" },
  podcast: { label: "Podcast" },
  document: { label: "Document" },
  tool: { label: "Tool" },
  other: { label: "Other" },
};

export const RESOURCE_STATUSES = [
  "inbox",
  "consuming",
  "completed",
  "saved",
] as const;
export type ResourceStatus = (typeof RESOURCE_STATUSES)[number];

export const RESOURCE_STATUS_META: Record<ResourceStatus, { label: string }> = {
  inbox: { label: "Inbox" },
  consuming: { label: "In progress" },
  completed: { label: "Finished" },
  saved: { label: "Saved" },
};

// ---------- Review ----------
export const REVIEW_TYPES = ["daily", "weekly", "monthly", "quarterly"] as const;
export type ReviewType = (typeof REVIEW_TYPES)[number];

export const REVIEW_TYPE_META: Record<ReviewType, { label: string }> = {
  daily: { label: "Daily" },
  weekly: { label: "Weekly" },
  monthly: { label: "Monthly" },
  quarterly: { label: "Quarterly" },
};

// ---------- Capture / Inbox ----------
export const INBOX_ITEM_TYPES = [
  "note",
  "task",
  "resource",
  "idea",
  "journal",
  "unknown",
] as const;
export type InboxItemType = (typeof INBOX_ITEM_TYPES)[number];

export const CAPTURE_SOURCES = [
  "web",
  "ios_app",
  "ios_widget",
  "share_extension",
  "siri_shortcut",
  "manual",
  "api",
] as const;
export type CaptureSource = (typeof CAPTURE_SOURCES)[number];

export const INBOX_STATUSES = ["inbox", "processed", "archived"] as const;
export type InboxStatus = (typeof INBOX_STATUSES)[number];
