"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import {
  CheckSquare,
  FolderKanban,
  LayoutGrid,
  NotebookPen,
  Layers,
  Target,
  Sparkles,
  Inbox,
  CalendarCheck,
  Plus,
  Search,
  ArrowRight,
  BookOpen,
  Users,
} from "lucide-react";
import type { SearchResult } from "@/lib/services/search";

const ENTITY_ICON: Record<SearchResult["entity"], React.ElementType> = {
  project: FolderKanban,
  task: CheckSquare,
  note: NotebookPen,
  resource: Layers,
  goal: Target,
  area: LayoutGrid,
};

/**
 * Global command palette (Cmd/Ctrl+K). Fuzzy list of quick actions plus live
 * search across all entities via /api/search. `onCapture` opens quick capture.
 */
export function CommandPalette({ onCapture }: { onCapture: () => void }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Debounced search.
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (!q) {
      setResults([]);
      return;
    }
    const id = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        setResults(data.results ?? []);
      } catch {
        setResults([]);
      }
    }, 150);
    return () => clearTimeout(id);
  }, [query, open]);

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      setQuery("");
      router.push(href);
    },
    [router]
  );

  const runCapture = useCallback(() => {
    setOpen(false);
    setQuery("");
    onCapture();
  }, [onCapture]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/30 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <Command
        label="Command palette"
        shouldFilter={false}
        onClick={(e) => e.stopPropagation()}
        className="animate-in w-full max-w-xl overflow-hidden rounded-[var(--radius-card)] border bg-[var(--surface)] shadow-[var(--shadow-md)]"
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="h-4 w-4 text-[var(--ink-3)]" />
          <Command.Input
            autoFocus
            value={query}
            onValueChange={setQuery}
            placeholder="Search or jump to…"
            className="h-11 w-full bg-transparent text-sm text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none"
          />
        </div>

        <Command.List className="max-h-[60vh] overflow-y-auto p-1.5">
          <Command.Empty className="px-3 py-6 text-center text-sm text-[var(--ink-3)]">
            No results.
          </Command.Empty>

          {results.length > 0 && (
            <Command.Group
              heading="Results"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-[var(--ink-3)]"
            >
              {results.map((r) => {
                const Icon = ENTITY_ICON[r.entity];
                return (
                  <Command.Item
                    key={`${r.entity}-${r.id}`}
                    value={`${r.entity}-${r.id}-${r.title}`}
                    onSelect={() => go(r.href)}
                    className="flex cursor-pointer items-center gap-2.5 rounded-[var(--radius-sm)] px-2 py-2 text-sm text-[var(--ink)] data-[selected=true]:bg-[var(--accent-soft)]"
                  >
                    <Icon className="h-4 w-4 text-[var(--ink-3)]" />
                    <span className="flex-1 truncate">{r.title}</span>
                    {r.subtitle && (
                      <span className="text-xs capitalize text-[var(--ink-3)]">{r.subtitle}</span>
                    )}
                  </Command.Item>
                );
              })}
            </Command.Group>
          )}

          <Command.Group
            heading="Actions"
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-[var(--ink-3)]"
          >
            <Action icon={Plus} label="Quick capture" onSelect={runCapture} hint="c" />
            <Action icon={Sparkles} label="Open Today" onSelect={() => go("/today")} hint="g t" />
            <Action icon={Inbox} label="Open Inbox" onSelect={() => go("/inbox")} hint="g i" />
            <Action icon={FolderKanban} label="New project" onSelect={() => go("/projects?new=1")} />
            <Action icon={CheckSquare} label="New task" onSelect={() => go("/tasks?new=1")} />
            <Action icon={NotebookPen} label="New note" onSelect={() => go("/notes?new=1")} />
            <Action icon={Layers} label="New resource" onSelect={() => go("/resources?new=1")} />
            <Action icon={CalendarCheck} label="Start a review" onSelect={() => go("/reviews?new=1")} />
            <Action icon={BookOpen} label="Open Knowledge" onSelect={() => go("/wiki")} hint="g w" />
            <Action icon={Users} label="Open Agent Center" onSelect={() => go("/teams")} hint="g e" />
          </Command.Group>
        </Command.List>
      </Command>
    </div>
  );
}

function Action({
  icon: Icon,
  label,
  onSelect,
  hint,
}: {
  icon: React.ElementType;
  label: string;
  onSelect: () => void;
  hint?: string;
}) {
  return (
    <Command.Item
      value={label}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2.5 rounded-[var(--radius-sm)] px-2 py-2 text-sm text-[var(--ink)] data-[selected=true]:bg-[var(--accent-soft)]"
    >
      <Icon className="h-4 w-4 text-[var(--ink-3)]" />
      <span className="flex-1">{label}</span>
      {hint ? (
        <kbd className="font-mono text-[10px] text-[var(--ink-3)]">{hint}</kbd>
      ) : (
        <ArrowRight className="h-3.5 w-3.5 text-[var(--ink-3)]" />
      )}
    </Command.Item>
  );
}
