import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { ResearchNav } from "@/components/layout/SectionNav";
import { NotebookEntryList } from "@/components/research/NotebookEntryList";
import { PageHeader, SectionCard } from "@/components/ui/primitives";
import { listLabProjects, listNotebookEntries } from "@/lib/services/labNotebook";
import { PROJECT_STATUS_META, type ProjectStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

/**
 * Every notebook entry that is off the working surface: entries archived one
 * by one (stored in VAULT/Research-Private/90_Archive/Lab Notebook/) and every
 * entry of a project that is not Active. Nothing here is deleted; Restore on an
 * entry, or setting its project back to Active, brings it back.
 */
export default async function NotebookArchivePage({
  searchParams,
}: {
  searchParams: Promise<{ project?: string; source?: string }>;
}) {
  const sp = await searchParams;
  const projects = await listLabProjects();
  const sourceFilter = sp.source === "onenote" || sp.source === "g2" ? sp.source : null;
  const withArchive = projects.filter((p) => !p.active && p.entryCount > 0);
  const chosen = withArchive.find((p) => p.code.toLowerCase() === (sp.project || "").toLowerCase());
  const everything = await listNotebookEntries(chosen?.code ?? null, "archive");
  const oneNoteCount = everything.filter((e) => e.source === "onenote").length;
  const entries = everything.filter((e) =>
    sourceFilter === "onenote" ? e.source === "onenote" : sourceFilter === "g2" ? e.source !== "onenote" : true,
  );
  const withSource = (href: string) =>
    sourceFilter ? `${href}${href.includes("?") ? "&" : "?"}source=${sourceFilter}` : href;
  const withProject = (source: string | null) => {
    const q = new URLSearchParams();
    if (chosen) q.set("project", chosen.code);
    if (source) q.set("source", source);
    const qs = q.toString();
    return `/research/notebook/archive${qs ? `?${qs}` : ""}`;
  };
  const statusLabel = Object.fromEntries(
    projects.map((p) => [
      p.code,
      p.planner
        ? (PROJECT_STATUS_META[p.planner.status as ProjectStatus]?.label ?? p.planner.status).toLowerCase()
        : "not in planner",
    ]),
  );

  return (
    <div>
      <ResearchNav />
      <Link
        href="/research/notebook"
        className="mb-2 inline-flex items-center gap-1 text-xs text-[var(--ink-2)] hover:text-[var(--accent-ink)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Lab notebook
      </Link>
      <PageHeader
        title="Notebook archive"
        subtitle="The notebooks of finished projects - every entry of a project marked Done (or otherwise not Active), OneNote imports included. Set a project back to Active and its notebook returns to the Lab notebook."
      />
      <div className="mb-2 flex flex-wrap gap-1.5">
        <Chip href={withProject(null)} active={!sourceFilter} label="All sources" />
        <Chip href={withProject("onenote")} active={sourceFilter === "onenote"} label={`OneNote (${oneNoteCount})`} />
        <Chip href={withProject("g2")} active={sourceFilter === "g2"} label="G2 entries" />
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5">
        <Chip href={withSource("/research/notebook/archive")} active={!chosen} label="All projects" />
        {withArchive.map((p) => (
          <Chip
            key={p.code}
            href={withSource(`/research/notebook/archive?project=${encodeURIComponent(p.code)}`)}
            active={chosen?.code === p.code}
            label={`${p.code} (${p.entryCount})`}
          />
        ))}
      </div>
      <SectionCard title={chosen ? `${chosen.code} archive` : "Finished projects"}>
        <NotebookEntryList
          entries={entries}
          showWhy
          projectStatus={statusLabel}
          empty={{
            title: "The archive is empty",
            description: "Mark a project Done in the Planner and its notebook moves here.",
          }}
        />
      </SectionCard>
    </div>
  );
}

function Chip({ href, active, label }: { href: string; active: boolean; label: string }) {
  return (
    <Link
      href={href}
      className={cn(
        "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent-ink)]"
          : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]",
      )}
    >
      {label}
    </Link>
  );
}
