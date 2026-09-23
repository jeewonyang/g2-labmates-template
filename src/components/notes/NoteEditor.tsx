"use client";

import { useOptimistic, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, Pencil, Pin, Trash2 } from "lucide-react";
import { deleteNoteAction, togglePinNoteAction, updateNoteAction } from "@/lib/actions";
import { Markdown } from "@/components/ui/Markdown";
import { Button } from "@/components/ui/primitives";
import { Input, Select, Textarea } from "@/components/ui/inputs";
import { cn } from "@/lib/utils";
import {
  NOTE_TYPES,
  NOTE_TYPE_META,
  type NoteType,
} from "@/lib/types";

/** View + inline-edit a note's title, type, markdown body, and pin state. */
export function NoteEditor({
  id,
  initialTitle,
  initialContent,
  initialType,
  pinned,
}: {
  id: string;
  initialTitle: string;
  initialContent: string;
  initialType: string;
  pinned: boolean;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(initialTitle);
  const [content, setContent] = useState(initialContent);
  const [type, setType] = useState<NoteType>(
    NOTE_TYPES.includes(initialType as NoteType)
      ? (initialType as NoteType)
      : "fleeting",
  );
  const [pending, start] = useTransition();
  const [savedAt, setSavedAt] = useState(false);
  // Optimistic: flips instantly on click, then settles on the server value
  // once the action's revalidation delivers the fresh page.
  const [optimisticPinned, setOptimisticPinned] = useOptimistic(pinned);

  const save = () =>
    start(async () => {
      await updateNoteAction(id, { title, type, contentMarkdown: content });
      setEditing(false);
      setSavedAt(true);
      setTimeout(() => setSavedAt(false), 1500);
      router.refresh();
    });

  const togglePin = () =>
    start(async () => {
      setOptimisticPinned(!optimisticPinned);
      await togglePinNoteAction(id);
      router.refresh();
    });

  const deleteNote = () => {
    if (!window.confirm(`Archive "${title}"? Its history will be retained.`)) return;
    start(async () => {
      await deleteNoteAction(id);
      router.push("/notes");
    });
  };

  return (
    <div>
      <div className="mb-3 flex items-start justify-between gap-3">
        {editing ? (
          <Input value={title} onChange={(e) => setTitle(e.target.value)} className="text-lg font-semibold" />
        ) : (
          <h1 className="text-2xl font-bold tracking-tight text-[var(--ink)]">{title}</h1>
        )}
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={togglePin}
            aria-label={optimisticPinned ? "Unpin" : "Pin"}
            className={cn("rounded p-1.5 hover:bg-[var(--surface-hover)]", optimisticPinned ? "text-[var(--accent)]" : "text-[var(--ink-3)]")}
          >
            <Pin className="h-4 w-4" fill={optimisticPinned ? "currentColor" : "none"} />
          </button>
          <Button
            variant="ghost"
            size="sm"
            onClick={deleteNote}
            aria-label="Delete note"
            title="Moves this note to the archive; it remains recoverable"
            className="text-[var(--red)]"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete
          </Button>
          {editing ? (
            <Button variant="primary" size="sm" onClick={save} disabled={pending}>
              {pending && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save
            </Button>
          ) : (
            <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
              <Pencil className="h-3.5 w-3.5" /> Edit
            </Button>
          )}
        </div>
      </div>

      {savedAt && (
        <p className="mb-2 flex items-center gap-1 text-xs text-[var(--green)]"><Check className="h-3 w-3" /> Saved</p>
      )}

      {editing ? (
        <div className="space-y-3">
          <label className="block max-w-xs text-xs font-medium text-[var(--ink-3)]">
            Note type
            <Select
              value={type}
              onChange={(event) => setType(event.target.value as NoteType)}
              className="mt-1"
              aria-label="Note type"
            >
              {NOTE_TYPES.map((noteType) => (
                <option key={noteType} value={noteType}>
                  {NOTE_TYPE_META[noteType].label}
                </option>
              ))}
            </Select>
          </label>
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={18}
            className="font-mono text-sm"
            placeholder="Write in markdown…"
          />
        </div>
      ) : content.trim() ? (
        <Markdown>{content}</Markdown>
      ) : (
        <p className="text-sm text-[var(--ink-3)]">Empty note. Click Edit to add content.</p>
      )}
    </div>
  );
}
