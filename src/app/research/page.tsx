import Link from "next/link";
import { BookOpen, Download, ExternalLink, Sparkles } from "lucide-react";
import { ResearchNav } from "@/components/layout/SectionNav";
import { BibliographyActions } from "@/components/research/BibliographyActions";
import { EmptyState, PageHeader, SectionCard } from "@/components/ui/primitives";
import { listAreas } from "@/lib/services/areas";
import { listProjects } from "@/lib/services/projects";
import { listResources } from "@/lib/services/resources";
import {
  describeResearchTarget,
  getBrainstormingAreaId,
  listBibliography,
  listRecentResearchReviews,
  type ResearchTarget,
} from "@/lib/services/research";

export const dynamic = "force-dynamic";

function citation(item: Awaited<ReturnType<typeof listBibliography>>[number]) {
  const authors = item.authorText || "Unknown authors";
  const year = item.publishedAt.slice(0, 4) || "n.d.";
  const venue = item.journal ? ` ${item.journal}.` : "";
  const doi = item.doi || item.preprintDoi;
  return `${authors} (${year}). ${item.title}.${venue}${doi ? ` https://doi.org/${doi}` : ""}`;
}

export default async function ResearchPage({
  searchParams,
}: {
  searchParams: Promise<{
    targetType?: string;
    targetId?: string;
    project?: string;
    unfiled?: string;
  }>;
}) {
  const params = await searchParams;
  const targetType: ResearchTarget["type"] =
    params.targetType === "resource"
      ? "resource"
      : params.targetType === "area"
        ? "area"
        : "project";
  const targetId = params.targetId || params.project || "";
  const selectedTarget: ResearchTarget | undefined = targetId
    ? { type: targetType, id: targetId }
    : undefined;
  const [allItems, items, reviews, projects, resources, areas, brainstormingId] =
    await Promise.all([
      listBibliography(),
      listBibliography(selectedTarget),
      listRecentResearchReviews(12),
      listProjects(),
      listResources(),
      listAreas(),
      getBrainstormingAreaId(),
    ]);
  const activeProjects = projects
    .filter((project) => project.status === "active")
    .map((project) => ({ id: project.id, title: project.title }));
  // Every unfiled paper is a Resource inside Brainstorming, so those rows are
  // excluded from the picker — otherwise the "Resources" group becomes the
  // bibliography again instead of a list of destinations.
  const brainstormedResourceIds = new Set(
    resources
      .filter((resource) => resource.area?.id === brainstormingId)
      .map((resource) => resource.id),
  );
  const resourceOptions = resources
    .filter((resource) => !brainstormedResourceIds.has(resource.id))
    .map((resource) => ({ id: resource.id, title: resource.title }));
  const areaOptions = areas
    .filter((area) => area.id !== brainstormingId)
    .map((area) => ({ id: area.id, title: area.title }));
  const projectTargets = uniqueTargets(allItems.flatMap((item) => item.projects));
  /*
    Category chips are destinations the owner chose, so they must stay a shortlist
    (the owner, 2026-08-27): a paper's own Brainstorming resource is not a
    category — six unfiled papers were rendering six "Resource · <paper>"
    chips. They collapse into the single "Brainstorming · unfiled" chip below,
    the same way the per-entry pill already reads.
  */
  const resourceTargets = uniqueTargets(
    allItems.flatMap((item) => item.resources),
  ).filter((resource) => !brainstormedResourceIds.has(resource.id));
  const areaTargets = uniqueTargets(allItems.flatMap((item) => item.areas)).filter(
    (area) => area.title.toLowerCase() !== "brainstorming",
  );
  const isUnfiled = (item: (typeof allItems)[number]) =>
    describeResearchTarget(item, brainstormedResourceIds).targetValue ===
    "brainstorming";
  const unfiledCount = allItems.filter(isUnfiled).length;
  const unfiledOnly = params.unfiled === "1" && !selectedTarget;
  const shownItems = unfiledOnly ? allItems.filter(isUnfiled) : items;

  return (
    <div>
      <ResearchNav />
      <PageHeader
        title="Rho research library"
        subtitle="Selected papers, durable review status, flexible classification, and Zotero-compatible bibliographies."
        actions={
          <Link
            href="/today"
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-3 py-1.5 text-xs font-medium text-[var(--accent-ink)] hover:bg-[var(--accent-soft)]"
          >
            <Sparkles className="h-3.5 w-3.5" />
            Review a paper
          </Link>
        }
      />

      <SectionCard title="Bibliography" className="mb-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Link
            href="/research"
            className={`rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs ${
              !selectedTarget && !unfiledOnly
                ? "bg-[var(--accent-soft)] text-[var(--accent-ink)]"
                : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
            }`}
          >
            All selected
          </Link>
          {projectTargets.map((project) => (
            <Link
              key={project.id}
              href={targetHref("project", project.id)}
              className={`rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs ${
                selectedTarget?.type === "project" &&
                selectedTarget.id === project.id
                  ? "bg-[var(--accent-soft)] text-[var(--accent-ink)]"
                  : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Project · {project.title}
            </Link>
          ))}
          {resourceTargets.map((resource) => (
            <Link
              key={resource.id}
              href={targetHref("resource", resource.id)}
              className={`rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs ${
                selectedTarget?.type === "resource" &&
                selectedTarget.id === resource.id
                  ? "bg-[var(--accent-soft)] text-[var(--accent-ink)]"
                  : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Resource · {resource.title}
            </Link>
          ))}
          {areaTargets.map((area) => (
            <Link
              key={area.id}
              href={targetHref("area", area.id)}
              className={`rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs ${
                selectedTarget?.type === "area" &&
                selectedTarget.id === area.id
                  ? "bg-[var(--accent-soft)] text-[var(--accent-ink)]"
                  : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Area · {area.title}
            </Link>
          ))}
          {unfiledCount > 0 && (
            <Link
              href="/research?unfiled=1"
              className={`rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs ${
                unfiledOnly
                  ? "bg-[var(--amber-soft)] text-[var(--amber)]"
                  : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
              }`}
            >
              Brainstorming · unfiled ({unfiledCount})
            </Link>
          )}
          {selectedTarget && (
            <a
              href={`/api/research/bibliography?targetType=${selectedTarget.type}&targetId=${encodeURIComponent(selectedTarget.id)}`}
              className="ml-auto inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-xs font-medium text-[var(--accent-ink)] hover:bg-[var(--accent-soft)]"
            >
              <Download className="h-3.5 w-3.5" />
              Export CSL-JSON
            </a>
          )}
        </div>

        {shownItems.length ? (
          <ol className="space-y-3">
            {shownItems.map((item, index) => (
              <li
                key={item.itemId}
                className="rounded-[var(--radius-sm)] border bg-[var(--surface-2)] p-3"
              >
                <div className="flex items-start gap-2">
                  <span className="font-mono text-xs text-[var(--ink-3)]">
                    {index + 1}.
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-relaxed text-[var(--ink)]">
                      {citation(item)}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {item.projects.map((project) => (
                        <span
                          key={project.id}
                          className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--accent-ink)]"
                        >
                          Project · {project.title}
                        </span>
                      ))}
                      {item.resources.map((resource) =>
                        brainstormedResourceIds.has(resource.id) ? (
                          // The paper's own row — labelling it "Resource · <the
                          // same title>" would just restate the citation above.
                          <span
                            key={resource.id}
                            className="rounded-full bg-[var(--amber-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--amber)]"
                          >
                            Brainstorming · unfiled
                          </span>
                        ) : (
                          <span
                            key={resource.id}
                            className="rounded-full bg-[var(--green-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--green)]"
                          >
                            Resource · {resource.title}
                          </span>
                        ),
                      )}
                      {item.areas.map((area) => (
                        <span
                          key={area.id}
                          className="rounded-full bg-[var(--amber-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--amber)]"
                        >
                          Area · {area.title}
                        </span>
                      ))}
                      {item.digestPath && (
                        <Link
                          href={`/vault/${item.digestPath}`}
                          className="inline-flex items-center gap-1 text-xs text-[var(--green)] hover:underline"
                        >
                          <BookOpen className="h-3.5 w-3.5" />
                          Review summary
                        </Link>
                      )}
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-[var(--ink-3)] hover:text-[var(--ink)]"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                          Article
                        </a>
                      )}
                    </div>
                    <BibliographyActions
                      itemId={item.itemId}
                      currentTarget={
                        describeResearchTarget(item, brainstormedResourceIds)
                          .targetValue
                      }
                      projects={activeProjects}
                      resources={resourceOptions}
                      areas={areaOptions}
                    />
                  </div>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState
            title="No papers selected"
            description="Ask Rho to review an article or DOI. A paper with no destination becomes its own resource in the Brainstorming domain, ready to move later."
          />
        )}
      </SectionCard>

      <SectionCard title="Recent Rho reviews">
        {reviews.length ? (
          <ul className="divide-y">
            {reviews.map((review) => (
              <li key={review.jobId} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-[var(--ink)]">
                    {review.title}
                  </p>
                  {review.error && (
                    <p className="line-clamp-1 text-xs text-[var(--red)]">
                      {review.error}
                    </p>
                  )}
                </div>
                <span className="rounded-full bg-[var(--surface-2)] px-2 py-0.5 font-mono text-[10px] uppercase text-[var(--ink-3)]">
                  {review.status.replace("_", " ")}
                </span>
                {review.digestPath && (
                  <Link
                    href={`/vault/${review.digestPath}`}
                    className="text-xs text-[var(--accent-ink)] hover:underline"
                  >
                    Open
                  </Link>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-[var(--ink-3)]">No Rho reviews yet.</p>
        )}
      </SectionCard>
    </div>
  );
}

function uniqueTargets(targets: Array<{ id: string; title: string }>) {
  return [...new Map(targets.map((target) => [target.id, target])).values()];
}

function targetHref(type: "project" | "resource" | "area", id: string) {
  return `/research?targetType=${type}&targetId=${encodeURIComponent(id)}`;
}
