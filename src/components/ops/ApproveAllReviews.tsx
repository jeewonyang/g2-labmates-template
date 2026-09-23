"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCheck, Loader2, XCircle } from "lucide-react";

/**
 * The two bulk motions of a review pass, in one control.
 *
 * (The file keeps its old `ApproveAllReviews` name; only the export was
 * generalized. One shared component per UI idea — "decide everything on
 * screen at once" is one idea with two polarities, and a second near-identical
 * component would be the duplicated-affordance mistake this repo keeps making.)
 *
 * The review queue was one decision per item even after you had already read
 * it. The way it is actually reviewed is subtractive — reject the few that are
 * wrong, then accept everything left — so "Approve remaining" is the accept
 * half. "Reject all" is the other end: a run that is wrong wholesale (a bad
 * classifier pass, a scan that produced noise) should not be N clicks either.
 *
 * Both act on fixed id lists computed on the server and rendered into this
 * component, not "everything in needs_review" resolved at click time. So they
 * can only ever touch what was on screen when the page rendered: a job that
 * arrives while you are reading is not swept in silently, it shows up on the
 * next refresh with its own buttons.
 *
 * **The two lists are deliberately different sizes.** Approving has an effect
 * — filing into the vault, and for one kind inserting a calendar event — so it
 * holds items back (see page.tsx):
 *   - `admin.schedule_proposal` — inserting a calendar event is one of the two
 *     writes that leave this machine, and SOUL.md says the owner approves *the
 *     specific item*. A bulk sweep is not that.
 *   - Confidential destinations, plus the batches listReviewBatches already
 *     flags requiresPerItem (unclassified, leave-in-inbox, new 10_Projects
 *     folders).
 *   - Create-then-reclassify batches, whose approval is a taxonomy change
 *     rather than a filing decision.
 *
 * Rejecting holds nothing back, because rejecting is the *conservative*
 * outcome of every one of those cases: no file is copied, no calendar event is
 * created, nothing is deleted, and the capture stays in its inbox. It is a
 * ledger transition (`needs_review -> rejected`) and the append-only history
 * keeps the proposal it declined. A declined `triage.classify` is also a
 * teaching signal, so the reason says it came from a sweep rather than from
 * reading one item.
 *
 * Approving is only the ledger transition; /api/ops spawns apply_jobs.py, which
 * files under APPLY_LOCK. Nothing here is a send.
 */

/** /api/ops caps a request at 500 ids; stay well under and chunk. */
const CHUNK = 200;

/** Distinguishes a swept decline from a considered one in the lessons log. */
const BULK_REJECT_REASON = "rejected in bulk from /ops";

const PILL =
  "inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 py-1 text-xs font-medium transition-opacity disabled:opacity-50";

export function BulkReviewActions({
  approvableJobIds,
  rejectableJobIds,
  heldBack,
}: {
  approvableJobIds: string[];
  rejectableJobIds: string[];
  heldBack: number;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function run(
    action: "approve" | "reject",
    jobIds: string[],
    reason?: string,
  ) {
    setBusy(action);
    setMessage(null);
    setFailed(false);
    let done = 0;
    try {
      for (let i = 0; i < jobIds.length; i += CHUNK) {
        const chunk = jobIds.slice(i, i + CHUNK);
        const res = await fetch("/api/ops", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, jobIds: chunk, reason }),
        });
        const body = (await res.json().catch(() => ({}))) as {
          applied?: number;
          error?: string;
          failed?: unknown[];
        };
        if (!res.ok && res.status !== 207) {
          throw new Error(body.error ?? `Request failed (${res.status}).`);
        }
        done += body.applied ?? 0;
      }
      const missed = jobIds.length - done;
      setFailed(missed > 0);
      if (missed > 0) {
        setMessage(
          `${action === "approve" ? "Approved" : "Rejected"} ${done}; ${missed} could not be ${
            action === "approve" ? "approved" : "rejected"
          }.`,
        );
      } else {
        setMessage(
          action === "approve"
            ? `Approved ${done}. Filing runs in the background.`
            : `Rejected ${done}. Nothing was filed; the captures stay where they are.`,
        );
      }
      router.refresh();
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : String(error));
      // A chunk may have landed before the failure, so re-read the queue.
      router.refresh();
    } finally {
      setBusy(null);
    }
  }

  function approveAll() {
    const n = approvableJobIds.length;
    if (
      !window.confirm(
        `Approve the remaining ${n} item${n === 1 ? "" : "s"}? They will be filed into the vault.` +
          (heldBack > 0
            ? `\n\n${heldBack} item${
                heldBack === 1 ? "" : "s"
              } still need an individual decision and will be left alone.`
            : "") +
          `\n\nReject anything you do not want first — this approves everything else.`,
      )
    ) {
      return;
    }
    void run("approve", approvableJobIds);
  }

  function rejectAll() {
    const n = rejectableJobIds.length;
    if (
      !window.confirm(
        `Reject all ${n} item${n === 1 ? "" : "s"} waiting here?` +
          `\n\nNothing is filed, nothing is sent, and nothing is deleted — captures stay in their inbox, proposals are dropped, and the full history stays in the ledger.` +
          `\n\nApprove anything you want to keep first — this rejects everything else, including the items that "Approve remaining" leaves alone.`,
      )
    ) {
      return;
    }
    void run("reject", rejectableJobIds, BULK_REJECT_REASON);
  }

  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-2">
      {message && (
        <span
          role="alert"
          className={
            failed ? "text-xs text-[var(--red)]" : "text-xs text-[var(--ink-3)]"
          }
        >
          {message}
        </span>
      )}
      {approvableJobIds.length > 1 && (
        <button
          type="button"
          onClick={approveAll}
          disabled={busy !== null}
          title={
            heldBack > 0
              ? `Approve the ${approvableJobIds.length} items that can be decided in bulk. ${heldBack} still need an individual decision.`
              : "Approve every item waiting here. Reject the ones you do not want first."
          }
          className={`${PILL} bg-[var(--accent)] text-white`}
        >
          {busy === "approve" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <CheckCheck className="h-3.5 w-3.5" />
          )}
          {busy === "approve"
            ? "Approving…"
            : `Approve remaining ${approvableJobIds.length}`}
        </button>
      )}
      {rejectableJobIds.length > 1 && (
        <button
          type="button"
          onClick={rejectAll}
          disabled={busy !== null}
          title="Decline everything waiting here. Nothing is filed and nothing is deleted — captures stay in their inbox."
          className={`${PILL} border border-[var(--red)] text-[var(--red)] hover:bg-[var(--red-soft)]`}
        >
          {busy === "reject" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <XCircle className="h-3.5 w-3.5" />
          )}
          {busy === "reject"
            ? "Rejecting…"
            : `Reject all ${rejectableJobIds.length}`}
        </button>
      )}
    </span>
  );
}
