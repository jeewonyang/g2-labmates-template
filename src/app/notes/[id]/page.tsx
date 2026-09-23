import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Link2, ExternalLink } from "lucide-react";
import { getNote } from "@/lib/services/notes";
import { SectionCard } from "@/components/ui/primitives";
import { NoteTypeBadge } from "@/components/ui/Badge";
import { NoteEditor } from "@/components/notes/NoteEditor";
import { PlannerNav } from "@/components/layout/SectionNav";

export const dynamic = "force-dynamic";

export default async function NoteDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const note = await getNote(id);
  if (!note) notFound();

  const backlinks = [...note.linkedNotes, ...note.linkedFrom].filter(
    (n, i, arr) => arr.findIndex((x) => x.id === n.id) === i
  );

  return (
    <div>
      <PlannerNav />
      <Link href="/notes" className="mb-3 inline-flex items-center gap-1 text-sm text-[var(--ink-3)] hover:text-[var(--ink)]">
        <ArrowLeft className="h-4 w-4" /> Notes
      </Link>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <NoteTypeBadge type={note.type} />
            {note.sourceUrl && (
              <a href={note.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-[var(--accent-ink)] hover:underline">
                <ExternalLink className="h-3 w-3" /> Source
              </a>
            )}
          </div>
          <NoteEditor
            id={note.id}
            initialTitle={note.title}
            initialContent={note.contentMarkdown}
            initialType={note.type}
            pinned={note.pinned}
          />
        </div>

        <div className="space-y-4">
          <SectionCard title="Links">
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between gap-2">
                <dt className="text-[var(--ink-3)]">Project</dt>
                <dd className="text-right">{note.project ? <Link href={`/projects/${note.project.id}`} className="text-[var(--accent-ink)] hover:underline">{note.project.title}</Link> : "—"}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-[var(--ink-3)]">Area</dt>
                <dd className="text-right">{note.area ? <Link href={`/areas/${note.area.id}`} className="text-[var(--accent-ink)] hover:underline">{note.area.title}</Link> : "—"}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-[var(--ink-3)]">Resource</dt>
                <dd className="text-right">{note.resource ? <Link href={`/resources/${note.resource.id}`} className="text-[var(--accent-ink)] hover:underline">{note.resource.title}</Link> : "—"}</dd>
              </div>
            </dl>
          </SectionCard>

          <SectionCard title={<span className="flex items-center gap-1.5"><Link2 className="h-4 w-4 text-[var(--ink-3)]" />Backlinks</span>}>
            {backlinks.length ? (
              <ul className="space-y-1.5">
                {backlinks.map((n) => (
                  <li key={n.id}>
                    <Link href={`/notes/${n.id}`} className="block truncate text-sm text-[var(--ink-2)] hover:text-[var(--accent-ink)]">
                      {n.title}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--ink-3)]">No linked notes yet.</p>
            )}
          </SectionCard>

          {note.tasks.length > 0 && (
            <SectionCard title="Related tasks">
              <ul className="space-y-1.5">
                {note.tasks.map((t) => (
                  <li key={t.id} className="truncate text-sm text-[var(--ink-2)]">{t.title}</li>
                ))}
              </ul>
            </SectionCard>
          )}
        </div>
      </div>
    </div>
  );
}
