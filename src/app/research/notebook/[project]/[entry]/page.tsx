import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { ResearchNav } from "@/components/layout/SectionNav";
import { NotebookBadges } from "@/components/research/NotebookBadges";
import { Badge } from "@/components/ui/Badge";
import { NotebookEntryDialog } from "@/components/research/NotebookEntryDialog";
import { NotebookTasksButton } from "@/components/research/NotebookTasksButton";
import { CopyButton } from "@/components/ui/CopyButton";
import { Card } from "@/components/ui/primitives";
import { VaultDocument } from "@/components/vault/VaultDocument";
import { getNotebookEntry, listLabProjects, sectionsOf } from "@/lib/services/labNotebook";

export const dynamic = "force-dynamic";

export default async function NotebookEntryPage({
  params,
}: {
  params: Promise<{ project: string; entry: string }>;
}) {
  const { project, entry: name } = await params;
  const entry = await getNotebookEntry(decodeURIComponent(project), decodeURIComponent(name));
  if (!entry) notFound();
  const projects = await listLabProjects();
  // Where an entry shows follows its project's status, not its file.
  const inArchive = !projects.find((p) => p.code === entry.projectCode)?.active;
  const sections = sectionsOf(entry.body);

  return (
    <div>
      <ResearchNav />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link
          href={
            inArchive
              ? `/research/notebook/archive?project=${entry.projectCode}`
              : `/research/notebook?project=${entry.projectCode}`
          }
          className="inline-flex items-center gap-1 text-xs text-[var(--ink-2)] hover:text-[var(--accent-ink)]"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> {entry.projectCode} {inArchive ? "archive" : "notebook"}
        </Link>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {inArchive && <Badge tone="purple">finished project</Badge>}
          {entry.source === "onenote" && <Badge tone="blue">OneNote</Badge>}
          {entry.loggedBy === "auto" && <Badge tone="purple">Auto-logged</Badge>}
          <NotebookBadges assay={entry.assay} outcome={entry.outcome} status={entry.status} />
          <NotebookTasksButton projectCode={entry.projectCode} entryName={entry.name} count={entry.nextSteps.length} />
          <NotebookEntryDialog
            projects={projects.map((p) => ({ code: p.code }))}
            existing={{
              projectCode: entry.projectCode,
              entryName: entry.name,
              values: {
                experimentId: entry.experimentId,
                date: entry.date,
                name: entry.label,
                summary: entry.summary,
                assay: entry.assay,
                outcome: entry.outcome,
                status: entry.status,
                inputPath: entry.inputPath,
                resultPath: entry.resultPath,
                introduction: sections.Introduction,
                objective: sections.Objective,
                materialsMethods: sections["Materials & Methods"],
                result: sections.Result,
                conclusion: sections.Conclusion,
                nextSteps: entry.nextSteps.join("\n"),
              },
            }}
          />
        </span>
      </div>

      <Card className="mb-4 space-y-1.5 px-4 py-3 text-xs">
        {entry.source === "onenote" && (
          <p className="text-[11px] text-[var(--ink-3)]">
            Imported from OneNote, page &ldquo;{entry.fm.source_page}&rdquo;
            {entry.fm.source_parent ? ` (topic “${entry.fm.source_parent}”)` : ""} · kept verbatim; images and
            attachments stay in OneNote{entry.fm.also_in ? ` · same page also filed under ${entry.fm.also_in}` : ""}
          </p>
        )}
        <DataPath label="Input data" value={entry.inputPath} />
        <DataPath label="Result data" value={entry.resultPath} />
        {entry.fm.code_repo && (
          <>
            <DataPath label="Code" value={entry.fm.code_remote || entry.fm.code_repo} />
            {entry.fm.code_diff && <DataPath label="Code diff" value={entry.fm.code_diff} />}
            <p className="pl-[5.5rem] text-[11px] text-[var(--ink-3)]">
              {[
                entry.fm.code_branch,
                entry.fm.code_commit ? `commit ${entry.fm.code_commit.slice(0, 12)}` : "no commit",
                entry.fm.code_dirty === "no" ? "clean" : entry.fm.code_dirty ? `uncommitted: ${entry.fm.code_dirty}` : "",
                entry.fm.environment,
                entry.fm.code_captured ? `captured ${entry.fm.code_captured.slice(0, 16).replace("T", " ")}` : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </>
        )}
        {(entry.fm.ai_model || entry.fm.prompt_summary) && (
          <>
            <DataPath
              label="AI"
              value={[
                entry.fm.ai_model,
                entry.fm.session_id ? `session ${entry.fm.session_id.slice(0, 8)}` : "",
                LOGGED_BY[entry.loggedBy] ?? entry.loggedBy,
              ]
                .filter(Boolean)
                .join(" · ")}
            />
            {entry.fm.prompt_summary && (
              <p className="pl-[5.5rem] text-[11px] text-[var(--ink-3)]">Prompt: {entry.fm.prompt_summary}</p>
            )}
          </>
        )}
        <p className="text-[11px] text-[var(--ink-3)]">
          {entry.relPath}
          {entry.fm.run_id ? ` · run ${entry.fm.run_id.slice(0, 8)}` : ""}
          {entry.fm.negative_result_id ? ` · negative-result ledger ${entry.fm.negative_result_id}` : ""}
        </p>
      </Card>

      <Card className="px-5 py-4">
        <VaultDocument fm={entry.fm} body={entry.body} fallbackTitle={entry.name} />
      </Card>
    </div>
  );
}

const LOGGED_BY: Record<string, string> = {
  skill: "filed with the lab-notebook skill",
  auto: "auto-logged when the session ended",
  "lab-run": "LabSerf run",
};

function DataPath({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="w-20 shrink-0 font-medium text-[var(--ink-2)]">{label}</span>
      <code className="min-w-0 flex-1 break-all text-[var(--ink)]">{value || "—"}</code>
      {value && <CopyButton text={value} />}
    </div>
  );
}
