import { cn } from "@/lib/utils";
import {
  AREA_HEALTH_META,
  GOAL_STATUS_META,
  NOTE_TYPE_META,
  PRIORITY_META,
  PROJECT_STATUS_META,
  RESOURCE_STATUS_META,
  TASK_STATUS_META,
  type AreaHealth,
  type GoalStatus,
  type NoteType,
  type Priority,
  type ProjectStatus,
  type ResourceStatus,
  type TaskStatus,
} from "@/lib/types";

type Tone = "gray" | "green" | "amber" | "red" | "blue" | "purple" | "accent";

const TONE_CLASS: Record<Tone, string> = {
  gray: "bg-[var(--gray-soft)] text-[var(--ink-2)]",
  green: "bg-[var(--green-soft)] text-[var(--green)]",
  amber: "bg-[var(--amber-soft)] text-[var(--amber)]",
  red: "bg-[var(--red-soft)] text-[var(--red)]",
  blue: "bg-[var(--blue-soft)] text-[var(--blue)]",
  purple: "bg-[var(--purple-soft)] text-[var(--purple)]",
  accent: "bg-[var(--accent-soft)] text-[var(--accent-ink)]",
};

export function Badge({
  children,
  tone = "gray",
  dot = false,
  className,
}: {
  children: React.ReactNode;
  tone?: Tone;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ring-current/20",
        TONE_CLASS[tone],
        className
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />}
      {children}
    </span>
  );
}

const PRIORITY_TONE: Record<Priority, Tone> = {
  urgent: "red",
  high: "amber",
  medium: "blue",
  low: "gray",
};

export function PriorityBadge({ priority }: { priority: string }) {
  const p = (priority in PRIORITY_META ? priority : "medium") as Priority;
  return (
    <Badge tone={PRIORITY_TONE[p]} dot>
      {PRIORITY_META[p].label}
    </Badge>
  );
}

const TASK_STATUS_TONE: Record<TaskStatus, Tone> = {
  inbox: "gray",
  next: "blue",
  scheduled: "amber",
  waiting: "purple",
  someday: "gray",
  completed: "green",
  canceled: "gray",
};

export function TaskStatusBadge({ status }: { status: string }) {
  const s = (status in TASK_STATUS_META ? status : "inbox") as TaskStatus;
  return <Badge tone={TASK_STATUS_TONE[s]}>{TASK_STATUS_META[s].label}</Badge>;
}

const PROJECT_STATUS_TONE: Record<ProjectStatus, Tone> = {
  inbox: "gray",
  active: "blue",
  paused: "amber",
  completed: "green",
  archived: "gray",
};

export function ProjectStatusBadge({ status }: { status: string }) {
  const s = (status in PROJECT_STATUS_META ? status : "active") as ProjectStatus;
  return <Badge tone={PROJECT_STATUS_TONE[s]} dot>{PROJECT_STATUS_META[s].label}</Badge>;
}

const HEALTH_TONE: Record<AreaHealth, Tone> = {
  healthy: "green",
  needs_attention: "amber",
  at_risk: "red",
};

export function HealthBadge({ health }: { health: string }) {
  const h = (health in AREA_HEALTH_META ? health : "healthy") as AreaHealth;
  return <Badge tone={HEALTH_TONE[h]} dot>{AREA_HEALTH_META[h].label}</Badge>;
}

const GOAL_STATUS_TONE: Record<GoalStatus, Tone> = {
  not_started: "gray",
  in_progress: "blue",
  paused: "amber",
  completed: "green",
};

export function GoalStatusBadge({ status }: { status: string }) {
  const s = (status in GOAL_STATUS_META ? status : "not_started") as GoalStatus;
  return <Badge tone={GOAL_STATUS_TONE[s]} dot>{GOAL_STATUS_META[s].label}</Badge>;
}

const RESOURCE_STATUS_TONE: Record<ResourceStatus, Tone> = {
  inbox: "gray",
  consuming: "blue",
  completed: "green",
  saved: "purple",
};

export function ResourceStatusBadge({ status }: { status: string }) {
  const s = (status in RESOURCE_STATUS_META ? status : "inbox") as ResourceStatus;
  return <Badge tone={RESOURCE_STATUS_TONE[s]}>{RESOURCE_STATUS_META[s].label}</Badge>;
}

export function NoteTypeBadge({ type }: { type: string }) {
  const t = (type in NOTE_TYPE_META ? type : "fleeting") as NoteType;
  return <Badge tone="gray">{NOTE_TYPE_META[t].label}</Badge>;
}
