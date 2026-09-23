import Link from "next/link";
import { Archive } from "lucide-react";
import { ResearchNav } from "@/components/layout/SectionNav";
import { LabRunLauncher } from "@/components/research/LabRunLauncher";
import { LabRunMonitor } from "@/components/research/LabRunMonitor";
import { NotebookEntryDialog } from "@/components/research/NotebookEntryDialog";
import { NotebookEntryList } from "@/components/research/NotebookEntryList";
import { CollapsibleSectionCard } from "@/components/ui/CollapsibleCard";
import { LinkButton, PageHeader, SectionCard } from "@/components/ui/primitives";
import {
  getLabEnvironment,
  listLabProjects,
  listLabRuns,
  listNotebookEntries,
} from "@/lib/services/labNotebook";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

/**
 * The lab notebook: launch a LabSerf analysis, watch it run, and read what
 * each experiment found - for Active projects only (the owner, 2026-09-21).
 * Entries of projects that are Done, Paused, or archived, and entries archived
 * one by one, are on /research/notebook/archive. Entries are the markdown
 * under VAULT/Research-Private/ - private, local, never in git.
 */
export default async function LabNotebookPage({
  searchParams,
}: {
  searchParams: Promise<{ project?: string }>;
}) {
  const sp = await searchParams;
  const [projects, runs] = await Promise.all([listLabProjects(), listLabRuns(10)]);
  const activeProjects = projects.filter((p) => p.active);
  const active = activeProjects.find((p) => p.code.toLowerCase() === (sp.project || "").toLowerCase());
  const entries = await listNotebookEntries(active?.code ?? null, "active");
  const archivedTotal = projects.filter((p) => !p.active).reduce((n, p) => n + p.entryCount, 0);
  const env = getLabEnvironment();
  const options = activeProjects.map((p) => ({ code: p.code }));

  return (
    <div>
      <ResearchNav />
      <PageHeader
        title="Lab notebook"
        subtitle="Launch flow, ultrasound or primer-design jobs with the LabSerf agents; each run files an entry under its project. Every entry of an Active project is here, OneNote imports included; a Done project's notebook moves to the Archive. Status is set on the project in the Planner."
        actions={
          <>
            <LinkButton href="/research/notebook/archive" size="sm">
              <Archive className="h-3.5 w-3.5" /> Archive ({archivedTotal})
            </LinkButton>
            <NotebookEntryDialog projects={options} defaultProject={active?.code} />
          </>
        }
      />

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
        <CollapsibleSectionCard title="Launch an analysis" storageKey="lab-notebook-launch">
          <LabRunLauncher
            projects={options}
            defaultProject={active?.code}
            disabledReason={env.problems.length ? env.problems.join(" ") : null}
          />
        </CollapsibleSectionCard>
        <CollapsibleSectionCard title="Runs" storageKey="lab-notebook-runs">
          <LabRunMonitor initial={runs} />
        </CollapsibleSectionCard>
      </div>

      <div className="mt-4 mb-3 flex flex-wrap gap-1.5">
        <Chip
          href="/research/notebook"
          active={!active}
          label={`All active (${activeProjects.reduce((n, p) => n + p.entryCount, 0)})`}
        />
        {activeProjects.map((p) => (
          <Chip
            key={p.code}
            href={`/research/notebook?project=${encodeURIComponent(p.code)}`}
            active={active?.code === p.code}
            label={`${p.code} (${p.entryCount})`}
          />
        ))}
      </div>

      <SectionCard title={active ? `${active.code} notebook` : "Entries"}>
        <NotebookEntryList
          entries={entries}
          empty={{
            title: "No notebook entries yet",
            description:
              "Launch an analysis above, or log a bench experiment with New entry. Finished projects' notebooks are in the Archive.",
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
