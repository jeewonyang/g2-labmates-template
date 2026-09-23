import Link from "next/link";
import { Pin } from "lucide-react";
import { listNotes } from "@/lib/services/notes";
import { listProjects } from "@/lib/services/projects";
import { listAreas } from "@/lib/services/areas";
import { PageHeader, Card, EmptyState } from "@/components/ui/primitives";
import { NoteTypeBadge } from "@/components/ui/Badge";
import { NewNoteButton } from "@/components/forms/CreateForms";
import { DeleteNoteButton } from "@/components/notes/DeleteNoteButton";
import { NOTE_TYPES, NOTE_TYPE_META } from "@/lib/types";
import { cn } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import { PlannerNav } from "@/components/layout/SectionNav";

export const dynamic = "force-dynamic";

export default async function NotesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const [notes, projects, areas] = await Promise.all([
    listNotes({ type: sp.type, q: sp.q }),
    listProjects(),
    listAreas(),
  ]);

  const buildHref = (patch: Record<string, string | undefined>) => {
    const params = new URLSearchParams();
    const merged = { q: sp.q, type: sp.type, ...patch };
    for (const [k, v] of Object.entries(merged)) if (v) params.set(k, v);
    const qs = params.toString();
    return qs ? `/notes?${qs}` : "/notes";
  };

  return (
    <div>
      <PlannerNav />
      <PageHeader
        title="Notes"
        subtitle="Atomic thoughts, meeting notes, literature notes, and reflections."
        actions={
          <NewNoteButton
            projects={projects.map((p) => ({ id: p.id, title: p.title }))}
            areas={areas.map((a) => ({ id: a.id, title: a.title }))}
            openOnMount={sp.new === "1"}
          />
        }
      />

      <form action="/notes" className="mb-4">
        <input
          name="q"
          defaultValue={sp.q}
          placeholder="Search notes…"
          className="w-full max-w-md rounded-[var(--radius-sm)] border bg-[var(--surface)] px-3 py-2 text-sm text-[var(--ink)] placeholder:text-[var(--ink-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
        />
      </form>

      <div className="mb-4 flex flex-wrap gap-1.5 text-xs">
        <FilterChip href={buildHref({ type: undefined })} active={!sp.type} label="All types" />
        {NOTE_TYPES.map((t) => (
          <FilterChip key={t} href={buildHref({ type: t })} active={sp.type === t} label={NOTE_TYPE_META[t].label} />
        ))}
      </div>

      {notes.length === 0 ? (
        <EmptyState title="No notes found" description="Try a different search or create a new note." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {notes.map((n) => (
            <Link key={n.id} href={`/notes/${n.id}`}>
              <Card interactive className="group flex h-full flex-col p-4">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-medium text-[var(--ink)]">{n.title}</h3>
                  <span className="flex shrink-0 items-center gap-1">
                    {n.pinned && <Pin className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" fill="currentColor" />}
                    <DeleteNoteButton id={n.id} title={n.title} />
                  </span>
                </div>
                {n.contentMarkdown && (
                  <p className="mt-1 line-clamp-3 flex-1 text-sm text-[var(--ink-3)]">
                    {n.contentMarkdown.replace(/[#*_`>-]/g, "").slice(0, 160)}
                  </p>
                )}
                <div className="mt-3 flex items-center justify-between gap-2">
                  <NoteTypeBadge type={n.type} />
                  <span className="text-xs text-[var(--ink-3)]">
                    {formatDistanceToNow(new Date(n.updatedAt), { addSuffix: true })}
                  </span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChip({ href, active, label }: { href: string; active: boolean; label: string }) {
  return (
    <Link
      href={href}
      className={cn(
        "rounded-full border px-2.5 py-1 font-medium transition-colors",
        active ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent-ink)]" : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
      )}
    >
      {label}
    </Link>
  );
}
