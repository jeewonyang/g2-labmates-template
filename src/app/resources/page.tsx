import Link from "next/link";
import { ExternalLink } from "lucide-react";
import { listResources } from "@/lib/services/resources";
import { listAreas } from "@/lib/services/areas";
import { getBrainstormedResourceIds } from "@/lib/services/research";
import { PageHeader, Card, EmptyState } from "@/components/ui/primitives";
import { ResourceStatusBadge, Badge } from "@/components/ui/Badge";
import { NewResourceButton } from "@/components/forms/CreateForms";
import { EditResourceButton } from "@/components/forms/EditForms";
import { RESOURCE_TYPES, RESOURCE_TYPE_META } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PlannerNav } from "@/components/layout/SectionNav";

export const dynamic = "force-dynamic";

export default async function ResourcesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const [allResources, areas, brainstormedIds] = await Promise.all([
    listResources({ type: sp.type, status: sp.status, q: sp.q }),
    listAreas(),
    getBrainstormedResourceIds(),
  ]);
  /*
    Unfiled papers materialize their own Resource rows inside Brainstorming
    (2026-07-30 design) so the bibliography has a real target — but they are
    citations, not library entries the owner saved, and six of them showing up here
    read as resources they never added (the owner, 2026-08-27). They live on
    /research; this library shows only what the owner filed.
  */
  const resources = allResources.filter((r) => !brainstormedIds.has(r.id));
  const hiddenPapers = allResources.length - resources.length;

  const buildHref = (patch: Record<string, string | undefined>) => {
    const params = new URLSearchParams();
    const merged = { q: sp.q, type: sp.type, status: sp.status, ...patch };
    for (const [k, v] of Object.entries(merged)) if (v) params.set(k, v);
    const qs = params.toString();
    return qs ? `/resources?${qs}` : "/resources";
  };

  return (
    <div>
      <PlannerNav />
      <PageHeader
        title="Resources"
        subtitle="Your knowledge library — articles, books, videos, courses, and tools."
        actions={<NewResourceButton areas={areas.map((a) => ({ id: a.id, title: a.title }))} openOnMount={sp.new === "1"} />}
      />

      <form action="/resources" className="mb-4">
        <input
          name="q"
          defaultValue={sp.q}
          placeholder="Search resources…"
          className="w-full max-w-md rounded-[var(--radius-sm)] border bg-[var(--surface)] px-3 py-2 text-sm text-[var(--ink)] placeholder:text-[var(--ink-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
        />
      </form>

      <div className="mb-4 flex flex-wrap gap-1.5 text-xs">
        <FilterChip href={buildHref({ type: undefined })} active={!sp.type} label="All types" />
        {RESOURCE_TYPES.map((t) => (
          <FilterChip key={t} href={buildHref({ type: t })} active={sp.type === t} label={RESOURCE_TYPE_META[t].label} />
        ))}
      </div>

      {hiddenPapers > 0 && (
        <p className="mb-3 text-xs text-[var(--ink-3)]">
          {hiddenPapers} unfiled paper{hiddenPapers === 1 ? "" : "s"} from Rho
          reviews {hiddenPapers === 1 ? "is" : "are"} parked in Brainstorming —
          see the{" "}
          <Link href="/research?unfiled=1" className="text-[var(--accent-ink)] hover:underline">
            research library
          </Link>{" "}
          to file or archive them.
        </p>
      )}
      {resources.length === 0 ? (
        <EmptyState title="No resources found" description="Save an article, book, or video to your library." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {resources.map((r) => (
            <Card key={r.id} className="group flex h-full flex-col p-4">
              <div className="flex items-start justify-between gap-2">
                <Link href={`/resources/${r.id}`} className="font-medium text-[var(--ink)] hover:text-[var(--accent-ink)]">
                  {r.title}
                </Link>
                <div className="flex shrink-0 items-center gap-1">
                  {r.url && (
                    <a href={r.url} target="_blank" rel="noreferrer" aria-label="Open link" className="shrink-0 text-[var(--ink-3)] hover:text-[var(--accent-ink)]">
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  )}
                  <EditResourceButton
                    resource={{
                      id: r.id,
                      title: r.title,
                      url: r.url,
                      type: r.type,
                      status: r.status,
                      summary: r.summary,
                      projectId: r.projectId,
                      areaId: r.areaId,
                    }}
                    iconOnly
                  />
                </div>
              </div>
              {r.summary && <p className="mt-1 line-clamp-2 flex-1 text-sm text-[var(--ink-3)]">{r.summary}</p>}
              <div className="mt-3 flex items-center gap-1.5">
                <Badge tone="gray">{RESOURCE_TYPE_META[r.type as keyof typeof RESOURCE_TYPE_META]?.label ?? r.type}</Badge>
                <ResourceStatusBadge status={r.status} />
              </div>
            </Card>
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
