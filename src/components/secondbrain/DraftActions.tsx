"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  Loader2,
  Pencil,
  Save,
  UserCheck,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const RELATIONSHIP_GROUPS = [
  "Mentor/PI",
  "Mentee",
  "Collaborator",
  "Colleague",
] as const;

type BusyAction = "approve" | "dismiss" | "edit" | "classify";

export function DraftActions({
  filename,
  type,
  draftReply,
  relationshipGroup,
  relationshipStatus,
  relationshipRationale,
  replyEdited,
}: {
  filename: string;
  type: string;
  draftReply: string;
  relationshipGroup: string;
  relationshipStatus: "inferred" | "confirmed";
  relationshipRationale: string;
  replyEdited: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<BusyAction | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [editing, setEditing] = useState(false);
  const [reply, setReply] = useState(draftReply);
  const [savedReply, setSavedReply] = useState(draftReply);
  const [group, setGroup] = useState(relationshipGroup);
  const [savedGroup, setSavedGroup] = useState(relationshipGroup);
  const [savedConfirmed, setSavedConfirmed] = useState(
    relationshipStatus === "confirmed",
  );
  const [classificationStatus, setClassificationStatus] =
    useState(relationshipStatus);
  const [hasToneLesson, setHasToneLesson] = useState(replyEdited);

  async function post(body: Record<string, unknown>) {
    const response = await fetch("/api/secondbrain/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, ...body }),
    });
    const data = (await response.json().catch(() => ({}))) as {
      error?: string;
      learned?: boolean;
    };
    if (!response.ok) {
      throw new Error(data.error ?? `Request failed (${response.status}).`);
    }
    return data;
  }

  async function act(action: "approve" | "dismiss") {
    setBusy(action);
    setMsg(null);
    try {
      await post({ action });
      setMsg({
        ok: true,
        text:
          action === "approve"
            ? "Created in Gmail Drafts. Send it there when ready."
            : "Dismissed and archived.",
      });
      router.refresh();
    } catch (error) {
      setMsg({
        ok: false,
        text: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setBusy(null);
    }
  }

  async function saveClassification() {
    setBusy("classify");
    setMsg(null);
    try {
      await post({ action: "classify", relationshipGroup: group });
      setSavedGroup(group);
      setSavedConfirmed(true);
      setClassificationStatus("confirmed");
      setMsg({
        ok: true,
        text: `Confirmed as ${group}. Future drafts will reuse this category.`,
      });
      router.refresh();
    } catch (error) {
      setMsg({
        ok: false,
        text: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setBusy(null);
    }
  }

  async function saveEdit() {
    if (!reply.trim() || reply === savedReply) {
      setEditing(false);
      return;
    }
    setBusy("edit");
    setMsg(null);
    try {
      await post({ action: "edit", reply });
      setSavedReply(reply.trim());
      setReply(reply.trim());
      setHasToneLesson(true);
      setEditing(false);
      setMsg({
        ok: true,
        text: "Saved. Your edit was recorded as a tone example for future drafts.",
      });
      router.refresh();
    } catch (error) {
      setMsg({
        ok: false,
        text: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setBusy(null);
    }
  }

  const classificationChanged = group !== savedGroup;

  return (
    <div className="space-y-3">
      <div className="rounded-[var(--radius-sm)] border bg-[var(--surface-2)] p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-44 flex-1">
            <span className="mb-1 block text-xs font-semibold text-[var(--ink-2)]">
              Relationship category
            </span>
            <select
              value={group}
              onChange={(event) => {
                const next = event.target.value;
                setGroup(next);
                setClassificationStatus(
                  next === savedGroup && savedConfirmed
                    ? "confirmed"
                    : "inferred",
                );
              }}
              disabled={busy !== null}
              className="w-full rounded-[var(--radius-sm)] border bg-[var(--surface)] px-2.5 py-1.5 text-sm text-[var(--ink)]"
            >
              {RELATIONSHIP_GROUPS.map((candidate) => (
                <option key={candidate} value={candidate}>
                  {candidate}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={saveClassification}
            disabled={
              busy !== null ||
              (classificationStatus === "confirmed" && !classificationChanged)
            }
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--accent)] px-3 py-1.5 text-sm font-medium text-[var(--accent-ink)] hover:bg-[var(--accent-soft)] disabled:opacity-50"
          >
            {busy === "classify" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <UserCheck className="h-3.5 w-3.5" />
            )}
            {classificationStatus === "confirmed" && classificationChanged
              ? "Save category"
              : classificationStatus === "confirmed"
                ? "Category confirmed"
                : "Approve category"}
          </button>
          <span
            className={cn(
              "rounded-full px-2 py-1 font-mono text-[10px] uppercase",
              classificationStatus === "confirmed"
                ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
                : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
            )}
          >
            {classificationStatus}
          </span>
        </div>
        {relationshipRationale && (
          <p className="mt-2 text-xs leading-5 text-[var(--ink-3)]">
            AI rationale: {relationshipRationale}
          </p>
        )}
      </div>

      {editing && (
        <div>
          <label
            htmlFor={`reply-${filename}`}
            className="mb-1 block text-xs font-semibold text-[var(--ink-2)]"
          >
            Edit reply
          </label>
          <textarea
            id={`reply-${filename}`}
            value={reply}
            onChange={(event) => setReply(event.target.value)}
            rows={7}
            maxLength={20_000}
            className="w-full resize-y rounded-[var(--radius-sm)] border bg-[var(--surface)] p-3 text-sm leading-6 text-[var(--ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
          />
          <p className="mt-1 text-[10px] text-[var(--ink-3)]">
            Saving stores your version as a tone example for this person and
            relationship category.
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {editing ? (
          <>
            <button
              type="button"
              onClick={saveEdit}
              disabled={busy !== null || !reply.trim()}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
            >
              {busy === "edit" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              Save edit
            </button>
            <button
              type="button"
              onClick={() => {
                setReply(savedReply);
                setEditing(false);
              }}
              disabled={busy !== null}
              className="rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm text-[var(--ink-2)] hover:bg-[var(--surface-hover)] disabled:opacity-50"
            >
              Cancel edit
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm font-medium text-[var(--ink-2)] hover:bg-[var(--surface-hover)] disabled:opacity-50"
          >
            <Pencil className="h-3.5 w-3.5" />
            Edit reply
          </button>
        )}

        {type !== "slack" && (
          <button
            type="button"
            onClick={() => act("approve")}
            disabled={busy !== null || editing}
            title={editing ? "Save the reply edit first" : undefined}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy === "approve" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            Create Gmail draft
          </button>
        )}

        <button
          type="button"
          onClick={() => {
            if (window.confirm("Dismiss this draft and archive it?")) {
              void act("dismiss");
            }
          }}
          disabled={busy !== null}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-red-300 px-3 py-1.5 text-sm text-red-700 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:text-red-300 dark:hover:bg-red-950"
        >
          {busy === "dismiss" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <X className="h-3.5 w-3.5" />
          )}
          Dismiss draft
        </button>

        {hasToneLesson && (
          <span className="text-xs text-[var(--ink-3)]">
            Tone learned from your edit
          </span>
        )}
        {msg && (
          <span
            className={cn(
              "text-xs",
              msg.ok
                ? "text-[var(--green-ink,var(--accent-ink))]"
                : "text-red-500",
            )}
            role="status"
          >
            {msg.text}
          </span>
        )}
      </div>
    </div>
  );
}
