"use client";

import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, ListChecks, Loader2 } from "lucide-react";
import { proposeTasksAction, saveDailyNoteAction } from "@/lib/actions";
import { Button } from "@/components/ui/primitives";
import { TaskExtractDialog } from "@/components/tasks/TaskExtractDialog";
import type { TaskCandidate } from "@/lib/services/taskExtract";
import { formatDateInput } from "@/lib/utils";

const MIN_HEIGHT = 120;
const MAX_HEIGHT = 900;
const DEFAULT_HEIGHT = 196;
const HEIGHT_KEY = "note-height:daily";
const KEYBOARD_STEP = 24;

const clampHeight = (value: number) =>
  Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, Math.round(value)));

/**
 * Autosaving daily journal editor for the Today page.
 *
 * The textarea is resized by an explicit drag handle rather than the browser's
 * native `resize-y` grip: the grip is a 12px target that is close to unusable on
 * a tablet, and a natively-resized height lives only in an inline style, so it
 * vanished on every reload. The chosen height is per-browser localStorage for
 * the same reason `CollapsibleSectionCard` keeps its open state there — it is a
 * viewing preference, and one database row would make the desktop and a tablet
 * fight over it.
 */
export function DailyNoteEditor({ initialContent }: { initialContent: string }) {
  const router = useRouter();
  const [content, setContent] = useState(initialContent);
  const [saved, setSaved] = useState(true);
  const [height, setHeight] = useState(DEFAULT_HEIGHT);
  const [pending, start] = useTransition();
  const [proposing, startProposing] = useTransition();
  const [proposal, setProposal] = useState<{
    candidates: TaskCandidate[];
    projects: Array<{ id: string; title: string }>;
  } | null>(null);
  const [pulled, setPulled] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const drag = useRef<{ startY: number; startHeight: number } | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  // Read after mount rather than lazily in useState: the server render has no
  // localStorage, and seeding state from it directly would hydrate-mismatch.
  useEffect(() => {
    const stored = Number(window.localStorage.getItem(HEIGHT_KEY));
    if (Number.isFinite(stored) && stored > 0) setHeight(clampHeight(stored));
  }, []);

  const persistHeight = useCallback((value: number) => {
    window.localStorage.setItem(HEIGHT_KEY, String(value));
  }, []);

  const onChange = (value: string) => {
    setContent(value);
    setSaved(false);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      start(async () => {
        await saveDailyNoteAction(value);
        setSaved(true);
      });
    }, 800);
  };

  /**
   * Parse the editor's own text rather than what is on disk: the autosave is
   * debounced 800ms, so the newest line typed may not be persisted yet and
   * pulling would silently miss it.
   */
  const propose = () =>
    startProposing(async () => {
      setPulled(null);
      setProposal(await proposeTasksAction(content, { sections: true }));
    });

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    drag.current = { startY: e.clientY, startHeight: height };
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    setHeight(clampHeight(drag.current.startHeight + (e.clientY - drag.current.startY)));
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    persistHeight(height);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const delta = e.key === "ArrowDown" ? KEYBOARD_STEP : e.key === "ArrowUp" ? -KEYBOARD_STEP : 0;
    if (!delta) return;
    e.preventDefault();
    const next = clampHeight(height + delta);
    setHeight(next);
    persistHeight(next);
  };

  return (
    <div>
      <textarea
        aria-label="Daily note"
        value={content}
        onChange={(e) => onChange(e.target.value)}
        style={{ height }}
        placeholder="How's today going? Jot intentions, notes, reflections…"
        className="w-full resize-none rounded-[var(--radius-sm)] border bg-[var(--surface-2)] px-3 py-2 text-sm text-[var(--ink)] placeholder:text-[var(--ink-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      />
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Drag to resize the daily note"
        aria-valuenow={height}
        aria-valuemin={MIN_HEIGHT}
        aria-valuemax={MAX_HEIGHT}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={onKeyDown}
        onDoubleClick={() => { setHeight(DEFAULT_HEIGHT); persistHeight(DEFAULT_HEIGHT); }}
        className="group mt-1 flex touch-none cursor-ns-resize items-center justify-center py-1.5 focus-visible:outline-none"
      >
        <span className="h-[3px] w-10 rounded-full bg-[var(--border-strong)] transition-colors group-hover:bg-[var(--ink-3)] group-focus-visible:bg-[var(--accent)]" />
      </div>
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1 text-xs text-[var(--ink-3)]">
          {pending ? (
            <><Loader2 className="h-3 w-3 animate-spin" /> Saving…</>
          ) : saved ? (
            <><Check className="h-3 w-3 text-[var(--green)]" /> Saved</>
          ) : (
            <>Unsaved changes…</>
          )}
          {pulled !== null && (
            <span className="ml-1 text-[var(--green)]">
              · {pulled} task{pulled === 1 ? "" : "s"} created
            </span>
          )}
        </span>
        <Button
          size="sm"
          onClick={propose}
          disabled={proposing || !content.trim()}
          title="Turn @section headers and unchecked lines into real tasks"
        >
          {proposing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ListChecks className="h-3.5 w-3.5" />}
          Pull into tasks
        </Button>
      </div>

      {proposal && (
        <TaskExtractDialog
          open
          onClose={() => setProposal(null)}
          title="Pull today's note into tasks"
          candidates={proposal.candidates}
          projects={proposal.projects}
          target={{ status: "scheduled", scheduledDate: formatDateInput(new Date()) }}
          onCreated={(count) => {
            setPulled(count);
            router.refresh();
          }}
        />
      )}
    </div>
  );
}
