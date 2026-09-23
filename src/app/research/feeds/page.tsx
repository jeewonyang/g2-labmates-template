import { Suspense } from "react";
import { ResearchNav } from "@/components/layout/SectionNav";
import { PageHeader, SectionCard } from "@/components/ui/primitives";
import { ResearchTrends } from "@/components/home/ResearchTrends";
import { fetchJournalFeeds } from "@/lib/services/journals";
import { getBrainstormingAreaId } from "@/lib/services/research";
import { listProjects } from "@/lib/services/projects";
import { listResources } from "@/lib/services/resources";

export const dynamic = "force-dynamic";

/**
 * The live journal/publisher feeds, moved off /today on 2026-08-27 (the owner:
 * research gets its own space). The daily surface keeps the CEO Brief's
 * research digests; browsing newsletters is a research-desk activity, not a
 * daily-planning one.
 */
export default async function ResearchFeedsPage() {
  const [projects, resources, brainstormingId] = await Promise.all([
    listProjects(),
    listResources(),
    getBrainstormingAreaId(),
  ]);

  return (
    <div>
      <ResearchNav />
      <PageHeader
        title="Research newsletters"
        subtitle="Live journal and publisher feeds, updated daily. Request a Rho review or file a paper straight into the library."
      />
      <SectionCard title="Latest articles">
        <Suspense fallback={<JournalFeedSkeleton />}>
          <JournalFeedLoader
            projects={projects
              .filter((project) => project.status === "active")
              .map((project) => ({ id: project.id, title: project.title }))}
            // Papers filed to Brainstorming each become a resource of their
            // own; they are entries, not destinations, so they stay out of the
            // destination picker.
            resources={resources
              .filter((resource) => resource.area?.id !== brainstormingId)
              .map((resource) => ({ id: resource.id, title: resource.title }))}
          />
        </Suspense>
      </SectionCard>
    </div>
  );
}

async function JournalFeedLoader({
  projects,
  resources,
}: {
  projects: Array<{ id: string; title: string }>;
  resources: Array<{ id: string; title: string }>;
}) {
  const feeds = await fetchJournalFeeds();
  return (
    <ResearchTrends feeds={feeds} projects={projects} resources={resources} />
  );
}

function JournalFeedSkeleton() {
  return (
    <div className="animate-pulse space-y-3">
      <div className="flex gap-1">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="h-7 w-20 rounded-[var(--radius-sm)] bg-[var(--surface-2)]"
          />
        ))}
      </div>
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="space-y-1.5 py-2">
          <div className="h-3.5 w-4/5 rounded bg-[var(--surface-2)]" />
          <div className="h-3 w-2/5 rounded bg-[var(--surface-2)]" />
        </div>
      ))}
    </div>
  );
}
