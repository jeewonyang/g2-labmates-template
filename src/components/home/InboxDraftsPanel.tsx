"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Mail,
  MessageSquare,
  X,
} from "lucide-react";
import { CopyButton } from "@/components/ui/CopyButton";
import { cn } from "@/lib/utils";
import { DeleteAllDraftsButton } from "@/components/secondbrain/DeleteAllDraftsButton";

/**
 * Incoming messages and their draft replies, on the daily surface.
 *
 * "Check messages & calendar" said to check drafts below and there was nothing
 * below — the drafts lived only on /drafts, a page you had to know to visit.
 * Each row carries the incoming message *and* the reply, because the question
 * being answered here is "what did I miss", not just "what did G2 write".
 *
 * Rows are collapsed by default and separated by rules rather than nested
 * cards: a bordered box inside a bordered card is what makes a dashboard look
 * busy, and this panel sits in the same SectionCard shell as its neighbours so
 * its edges line up with them by construction.
 *
 * A row can be dismissed here (2026-07-31). Reading "what did I miss" and
 * deciding "that one needs nothing from me" are the same motion, and sending
 * you to /drafts to clear a row you had already read is what left this panel
 * showing stale work. It posts the same `dismiss` action /drafts posts, so the
 * draft is archived to drafts/expired/ with its feedback history intact —
 * dismissing is never a delete. Approving still lives on /drafts only: creating
 * a Gmail draft is an outbound write and belongs behind the fuller review.
 */

export interface DraftSummary {
  filename: string;
  type: string;
  recipient: string;
  subject: string;
  context: string;
  created: string;
  originalMessage: string;
  draftReply: string;
}

function stripQuoteMarkers(text: string): string {
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(/^>\s?/, ""))
    .join("\n")
    .trim();
}

export function InboxDraftsPanel({ drafts }: { drafts: DraftSummary[] }) {
  const router = useRouter();
  const [open, setOpen] = useState<string | null>(
    drafts.length === 1 ? drafts[0].filename : null,
  );
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The row is hidden as soon as the server confirms, rather than waiting for
  // router.refresh() to re-render the page — the round trip spawns Python, and
  // a row that sits there after you dismissed it reads as a failure.
  const visible = drafts.filter((d) => !dismissed.includes(d.filename));

  async function dismiss(filename: string) {
    setBusy(filename);
    setError(null);
    try {
      const response = await fetch("/api/secondbrain/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename, action: "dismiss" }),
      });
      const data = (await response.json().catch(() => ({}))) as {
        error?: string;
      };
      if (!response.ok) {
        throw new Error(data.error ?? `Request failed (${response.status}).`);
      }
      setDismissed((prev) => [...prev, filename]);
      setOpen((current) => (current === filename ? null : current));
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  if (visible.length === 0) {
    return (
      <div className="py-2">
        <p className="text-sm text-[var(--ink-2)]">Nothing waiting for a reply.</p>
        <p className="mt-1 text-xs text-[var(--ink-3)]">
          Use <span className="font-medium">Check messages &amp; calendar</span> above
          to sweep Gmail and Slack. Anything that needs an answer shows up here
          with a draft you can edit and copy.
        </p>
      </div>
    );
  }

  return (
    <div className="-my-1 divide-y divide-[var(--rule)]">
      {visible.map((draft) => {
        const isOpen = open === draft.filename;
        const isDismissing = busy === draft.filename;
        const incoming = stripQuoteMarkers(draft.originalMessage);
        const isSlack = draft.type === "slack";
        return (
          <div key={draft.filename} className="py-2.5">
            <div className="flex min-w-0 items-start gap-2.5">
              <button
                onClick={() => setOpen(isOpen ? null : draft.filename)}
                aria-expanded={isOpen}
                className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
              >
                <span className="mt-0.5 shrink-0 text-[var(--ink-3)]">
                  {isOpen ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-[var(--ink-3)]">
                    {isSlack ? (
                      <MessageSquare className="h-3 w-3" />
                    ) : (
                      <Mail className="h-3 w-3" />
                    )}
                    {isSlack ? "Slack" : "Email"}
                    {draft.created && <span>· {draft.created}</span>}
                  </span>
                  <span className="mt-0.5 block truncate text-sm font-medium text-[var(--ink)]">
                    {draft.recipient || "Unknown sender"}
                  </span>
                  <span className="block truncate text-xs text-[var(--ink-3)]">
                    {draft.subject || "(no subject)"}
                  </span>
                </span>
              </button>
              <CopyButton
                text={draft.draftReply}
                label="Copy reply"
                className="mt-0.5"
              />
              <button
                type="button"
                onClick={() => {
                  if (
                    window.confirm(
                      "Dismiss this draft? It's archived in drafts/expired, not deleted.",
                    )
                  ) {
                    void dismiss(draft.filename);
                  }
                }}
                disabled={busy !== null}
                title="Dismiss this draft (archives it, never deletes)"
                aria-label={`Dismiss draft for ${draft.recipient || "unknown sender"}`}
                className="mt-0.5 inline-flex shrink-0 items-center rounded-[var(--radius-sm)] border p-1 text-[var(--ink-3)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--ink-2)] disabled:opacity-40"
              >
                {isDismissing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <X className="h-3.5 w-3.5" />
                )}
              </button>
            </div>

            {isOpen && (
              <div className="mt-2.5 space-y-2.5 pl-6">
                {draft.context && (
                  <p className="text-xs italic text-[var(--ink-3)]">
                    {draft.context}
                  </p>
                )}
                <Field
                  label="They wrote"
                  body={incoming}
                  copyLabel="Copy message"
                  muted
                />
                <Field
                  label="Your draft reply"
                  body={draft.draftReply}
                  copyLabel="Copy reply"
                />
                <p className="text-[11px] text-[var(--ink-3)]">
                  {isSlack
                    ? "Slack is read-only — copy this and post it yourself."
                    : "Approve on the drafts page to put this in Gmail Drafts. Nothing is ever sent."}
                </p>
              </div>
            )}
          </div>
        );
      })}
      {error && (
        <p className="pt-2 text-xs text-[var(--red)]" role="status">
          Could not dismiss: {error}
        </p>
      )}
    </div>
  );
}

function Field({
  label,
  body,
  copyLabel,
  muted = false,
}: {
  label: string;
  body: string;
  copyLabel: string;
  muted?: boolean;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--ink-3)]">
          {label}
        </span>
        <CopyButton text={body} label={copyLabel} />
      </div>
      <p
        className={cn(
          "max-h-44 overflow-y-auto whitespace-pre-wrap rounded-[var(--radius-sm)] bg-[var(--bg)] px-2.5 py-2 text-xs leading-relaxed",
          muted ? "text-[var(--ink-3)]" : "text-[var(--ink-2)]",
        )}
      >
        {body || "(empty)"}
      </p>
    </div>
  );
}

export function DraftsPanelFooter({ count }: { count: number }) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      <DeleteAllDraftsButton count={count} compact />
      <Link
        href="/drafts"
        className="text-xs text-[var(--accent-ink)] hover:underline"
      >
        {count > 0 ? `All drafts (${count})` : "All drafts"}
      </Link>
    </span>
  );
}
