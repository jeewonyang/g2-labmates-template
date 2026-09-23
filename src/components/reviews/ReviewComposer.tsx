"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2 } from "lucide-react";
import { proposeTasksAction, saveReviewAction } from "@/lib/actions";
import { Button } from "@/components/ui/primitives";
import { Field, Input, Select, Textarea } from "@/components/ui/inputs";
import { TaskExtractDialog } from "@/components/tasks/TaskExtractDialog";
import type { TaskCandidate } from "@/lib/services/taskExtract";
import { REVIEW_TYPES, REVIEW_TYPE_META, type ReviewType } from "@/lib/types";
import { formatDateInput } from "@/lib/utils";

type Existing = {
  type: string;
  date: string;
  wins: string | null;
  challenges: string | null;
  lessons: string | null;
  priorities: string | null;
  contentMarkdown: string;
} | null;

/**
 * Compose or edit a review.
 *
 * A review is one upserted row per (type, date), so this is an edit-in-place
 * document, not a form that clears on submit. Changing type/date navigates;
 * `/reviews` keys this component on both so the fields actually reload — state
 * seeded from props alone silently kept the previous review's text and would
 * have saved it back under the newly selected date.
 *
 * The body no longer seeds from a markdown template. The template restated the
 * four structured fields as headings, so every saved review carried a block of
 * empty scaffold, and it was what made saving look like it had done nothing.
 */
export function ReviewComposer({
  initialType,
  initialDate,
  existing,
}: {
  initialType: ReviewType;
  initialDate: string;
  existing: Existing;
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [saved, setSaved] = useState(false);

  const [type, setType] = useState<ReviewType>(initialType);
  const [date, setDate] = useState(initialDate);
  const [wins, setWins] = useState(existing?.wins ?? "");
  const [challenges, setChallenges] = useState(existing?.challenges ?? "");
  const [lessons, setLessons] = useState(existing?.lessons ?? "");
  const [priorities, setPriorities] = useState(existing?.priorities ?? "");
  const [content, setContent] = useState(existing?.contentMarkdown ?? "");
  const [proposal, setProposal] = useState<{
    candidates: TaskCandidate[];
    projects: Array<{ id: string; title: string }>;
  } | null>(null);

  const reload = (nextType: ReviewType, nextDate: string) => {
    router.push(`/reviews?type=${nextType}&date=${nextDate}`);
  };

  /**
   * Saving also offers the priorities as tasks. Reflecting is only half a
   * review — the priorities written here are next actions, and until they
   * exist as tasks they live in a column nothing else in the app reads.
   */
  const save = () =>
    start(async () => {
      await saveReviewAction({
        type,
        date,
        wins: wins || undefined,
        challenges: challenges || undefined,
        lessons: lessons || undefined,
        priorities: priorities || undefined,
        contentMarkdown: content || undefined,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
      router.refresh();

      if (priorities.trim()) {
        const next = await proposeTasksAction(priorities, { sections: false });
        if (next.candidates.length) setProposal(next);
      }
    });

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Type">
          <Select
            value={type}
            onChange={(e) => {
              const t = e.target.value as ReviewType;
              setType(t);
              reload(t, date);
            }}
          >
            {REVIEW_TYPES.map((t) => <option key={t} value={t}>{REVIEW_TYPE_META[t].label}</option>)}
          </Select>
        </Field>
        <Field label="Date">
          <Input
            type="date"
            value={date}
            onChange={(e) => {
              setDate(e.target.value);
              reload(type, e.target.value);
            }}
          />
        </Field>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Wins"><Textarea rows={3} value={wins} onChange={(e) => setWins(e.target.value)} /></Field>
        <Field label="Challenges"><Textarea rows={3} value={challenges} onChange={(e) => setChallenges(e.target.value)} /></Field>
        <Field label="Lessons"><Textarea rows={3} value={lessons} onChange={(e) => setLessons(e.target.value)} /></Field>
        <Field label="Next priorities">
          <Textarea
            rows={3}
            value={priorities}
            onChange={(e) => setPriorities(e.target.value)}
            placeholder="One per line — you'll be offered these as tasks on save."
          />
        </Field>
      </div>

      <Field label="Anything else (optional)">
        <Textarea
          rows={4}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Markdown. Only for what the four fields above don't cover."
          className="font-mono text-sm"
        />
      </Field>

      <div className="flex items-center gap-3">
        <Button variant="primary" onClick={save} disabled={pending}>
          {pending && <Loader2 className="h-4 w-4 animate-spin" />} Save review
        </Button>
        {saved && <span className="flex items-center gap-1 text-sm text-[var(--green)]"><Check className="h-4 w-4" /> Saved</span>}
      </div>

      {proposal && (
        <TaskExtractDialog
          open
          onClose={() => setProposal(null)}
          title="Turn next priorities into tasks"
          candidates={proposal.candidates}
          projects={proposal.projects}
          target={{ status: "next" }}
          onCreated={() => router.refresh()}
        />
      )}
    </div>
  );
}

export { formatDateInput };
