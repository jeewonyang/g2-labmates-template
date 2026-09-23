"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { Archive, Bot, CheckSquare, Layers, NotebookPen, RefreshCw } from "lucide-react";
import {
  archiveInboxAction,
  processInboxAction,
  retryInboxAutomationAction,
} from "@/lib/actions";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

const SOURCE_LABEL: Record<string, string> = {
  web: "Web",
  ios_app: "iOS app",
  ios_widget: "Widget",
  share_extension: "Share sheet",
  siri_shortcut: "Siri",
  manual: "Manual",
  api: "API",
};

export type InboxItemData = {
  id: string;
  rawText: string;
  parsedTitle: string | null;
  type: string;
  source: string;
  sourceUrl: string | null;
  capturedAt: string | Date;
  tags: { id: string; name: string }[];
  automation: {
    state: string;
    confidence: number | null;
    destinationPath: string | null;
    error: string | null;
  } | null;
};

const AUTOMATION_LABEL: Record<string, string> = {
  queued: "Queued",
  local_triage: "Local triage",
  verifying: "Verifying",
  ready: "Ready to apply",
  applied: "Organized",
  needs_review: "Needs your input",
  failed: "Needs retry",
  overridden: "Manual",
};

export function InboxTriage({ items }: { items: InboxItemData[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="Inbox zero 🎉"
        description="Captured notes, tasks, links, and ideas land here. Process them into projects, tasks, notes, or resources."
      />
    );
  }
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <InboxRow key={item.id} item={item} />
      ))}
    </ul>
  );
}

function InboxRow({ item }: { item: InboxItemData }) {
  const router = useRouter();
  const [pending, start] = useTransition();

  const process = (into: "task" | "note" | "resource") =>
    start(async () => {
      await processInboxAction(item.id, into);
      router.refresh();
    });

  const archive = () =>
    start(async () => {
      await archiveInboxAction(item.id);
      router.refresh();
    });

  const retry = () =>
    start(async () => {
      await retryInboxAutomationAction(item.id);
      router.refresh();
    });

  return (
    <li
      className={cn(
        "rounded-[var(--radius-card)] border bg-[var(--surface)] p-3 shadow-[var(--shadow-sm)]",
        pending && "opacity-50"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-[var(--ink)]">
            {item.parsedTitle || item.rawText}
          </p>
          {item.parsedTitle && item.rawText !== item.parsedTitle && (
            <p className="mt-0.5 line-clamp-2 text-xs text-[var(--ink-3)]">{item.rawText}</p>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-[var(--ink-3)]">
            <Badge tone="accent">{item.type}</Badge>
            <span>· {SOURCE_LABEL[item.source] ?? item.source}</span>
            <span>· {formatDistanceToNow(new Date(item.capturedAt), { addSuffix: true })}</span>
            {item.tags.map((t) => (
              <span key={t.id} className="text-[var(--ink-3)]">#{t.name}</span>
            ))}
          </div>
          {item.automation && (
            <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 rounded-[var(--radius-sm)] bg-[var(--surface-hover)] px-2.5 py-2 text-xs">
              <Bot className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
              <span className="font-medium text-[var(--ink-2)]">
                {AUTOMATION_LABEL[item.automation.state] ?? item.automation.state}
              </span>
              {item.automation.confidence != null && (
                <span className="text-[var(--ink-3)]">
                  {Math.round(item.automation.confidence * 100)}% confidence
                </span>
              )}
              {item.automation.destinationPath && (
                <span className="max-w-full truncate font-mono text-[11px] text-[var(--ink-3)]">
                  {item.automation.destinationPath}
                </span>
              )}
              {item.automation.error && (
                <span className="basis-full text-[var(--red)]">
                  {item.automation.error}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <TriageBtn icon={CheckSquare} label="Task" onClick={() => process("task")} disabled={pending} />
        <TriageBtn icon={NotebookPen} label="Note" onClick={() => process("note")} disabled={pending} />
        <TriageBtn icon={Layers} label="Resource" onClick={() => process("resource")} disabled={pending} />
        <TriageBtn icon={Archive} label="Archive" onClick={archive} disabled={pending} muted />
        {item.automation?.state === "failed" && (
          <TriageBtn
            icon={RefreshCw}
            label="Retry automation"
            onClick={retry}
            disabled={pending}
          />
        )}
      </div>
    </li>
  );
}

function TriageBtn({
  icon: Icon,
  label,
  onClick,
  disabled,
  muted,
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  muted?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50",
        muted
          ? "text-[var(--ink-3)] hover:bg-[var(--surface-hover)]"
          : "text-[var(--ink-2)] hover:bg-[var(--accent-soft)] hover:text-[var(--accent-ink)]"
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
