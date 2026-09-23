import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { getResource } from "@/lib/services/resources";
import { PageHeader, SectionCard, EmptyState } from "@/components/ui/primitives";
import { ResourceStatusBadge, Badge } from "@/components/ui/Badge";
import { EditResourceButton } from "@/components/forms/EditForms";
import { RESOURCE_TYPE_META } from "@/lib/types";
import { PlannerNav } from "@/components/layout/SectionNav";

export const dynamic = "force-dynamic";

export default async function ResourceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const resource = await getResource(id);
  if (!resource) notFound();

  return (
    <div>
      <PlannerNav />
      <Link href="/resources" className="mb-3 inline-flex items-center gap-1 text-sm text-[var(--ink-3)] hover:text-[var(--ink)]">
        <ArrowLeft className="h-4 w-4" /> Resources
      </Link>
      <PageHeader
        title={resource.title}
        actions={
          <div className="flex items-center gap-2">
            <Badge tone="gray">{RESOURCE_TYPE_META[resource.type as keyof typeof RESOURCE_TYPE_META]?.label ?? resource.type}</Badge>
            <ResourceStatusBadge status={resource.status} />
            <EditResourceButton
              resource={{
                id: resource.id,
                title: resource.title,
                url: resource.url,
                type: resource.type,
                status: resource.status,
                summary: resource.summary,
                projectId: resource.projectId,
                areaId: resource.areaId,
              }}
            />
          </div>
        }
      />

      {resource.url && (
        <a
          href={resource.url}
          target="_blank"
          rel="noreferrer"
          className="mb-4 inline-flex items-center gap-1.5 text-sm text-[var(--accent-ink)] hover:underline"
        >
          <ExternalLink className="h-4 w-4" /> {resource.url}
        </a>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          <SectionCard title="Summary">
            {resource.summary ? (
              <p className="whitespace-pre-wrap text-sm text-[var(--ink-2)]">{resource.summary}</p>
            ) : (
              <p className="text-sm text-[var(--ink-3)]">No summary yet.</p>
            )}
          </SectionCard>

          <SectionCard title={`Notes · ${resource.notes.length}`}>
            {resource.notes.length ? (
              <ul className="divide-y">
                {resource.notes.map((n) => (
                  <li key={n.id}>
                    <Link href={`/notes/${n.id}`} className="block truncate py-2 text-sm text-[var(--ink)] hover:opacity-80">
                      {n.title}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No notes" description="Notes you link to this resource show up here." />
            )}
          </SectionCard>
        </div>

        <SectionCard title="Details">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--ink-3)]">Area</dt>
              <dd className="text-right">{resource.area ? <Link href={`/areas/${resource.area.id}`} className="text-[var(--accent-ink)] hover:underline">{resource.area.title}</Link> : "—"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-[var(--ink-3)]">Project</dt>
              <dd className="text-right">{resource.project ? <Link href={`/projects/${resource.project.id}`} className="text-[var(--accent-ink)] hover:underline">{resource.project.title}</Link> : "—"}</dd>
            </div>
            {resource.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {resource.tags.map((t) => <span key={t.id} className="text-xs text-[var(--ink-3)]">#{t.name}</span>)}
              </div>
            )}
          </dl>
        </SectionCard>
      </div>
    </div>
  );
}
