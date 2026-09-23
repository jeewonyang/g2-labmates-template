"use client";

import { useTransition } from "react";
import { Trash2 } from "lucide-react";
import { deleteNoteAction } from "@/lib/actions";
import { cn } from "@/lib/utils";

/**
 * Hover-revealed delete button for note cards. Cards are wrapped in a Link,
 * so the click must not bubble into navigation.
 */
export function DeleteNoteButton({ id, title }: { id: string; title: string }) {
  const [pending, start] = useTransition();
  return (
    <button
      aria-label="Delete note"
      title="Moves this note to the archive; it remains recoverable"
      disabled={pending}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!window.confirm(`Archive "${title}"? Its history will be retained.`)) return;
        start(() => void deleteNoteAction(id));
      }}
      className={cn(
        "shrink-0 rounded p-1 text-[var(--ink-3)] transition-opacity hover:bg-[var(--surface-hover)] hover:text-[var(--red)] focus-visible:opacity-100",
        pending ? "opacity-50" : "opacity-70 hover:opacity-100"
      )}
    >
      <Trash2 className="h-3.5 w-3.5" />
    </button>
  );
}
