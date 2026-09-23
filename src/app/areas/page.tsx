import Link from "next/link";
import { PlannerNav } from "@/components/layout/SectionNav";
import { listAreas } from "@/lib/services/areas";
import { PageHeader, Card, EmptyState } from "@/components/ui/primitives";
import { HealthBadge, Badge } from "@/components/ui/Badge";
import { NewAreaButton } from "@/components/forms/CreateForms";
import { EditAreaButton } from "@/components/forms/EditForms";

export const dynamic = "force-dynamic";

export default async function AreasPage() {
  const areas = await listAreas();
  const responsibilities = areas.filter((a) => a.type === "area");
  const resources = areas.filter((a) => a.type === "resource");

  return (
    <div>
      <PlannerNav />
      <PageHeader
        title="Areas"
        subtitle="Ongoing responsibilities and domains you maintain over time."
        actions={
          <>
            <Link href="/goals" className="text-sm text-[var(--accent-ink)] hover:underline">
              Goals
            </Link>
            <NewAreaButton />
          </>
        }
      />

      {areas.length === 0 ? (
        <EmptyState title="No areas yet" description="Areas are the life and work domains you maintain — health, finance, research, and so on." />
      ) : (
        <div className="space-y-6">
          <AreaGroup title="Responsibilities" areas={responsibilities} />
          <AreaGroup title="Resource domains" areas={resources} />
        </div>
      )}
    </div>
  );
}

function AreaGroup({
  title,
  areas,
}: {
  title: string;
  areas: Awaited<ReturnType<typeof listAreas>>;
}) {
  if (!areas.length) return null;
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-[var(--ink-2)]">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {/*
          The card is no longer one big Link: the edit control has to be
          clickable without navigating, and a button nested inside an anchor
          cannot be. The title carries the navigation instead.
        */}
        {areas.map((a) => (
          <Card key={a.id} className="group h-full p-4">
            <div className="flex items-start justify-between gap-2">
              <Link
                href={`/areas/${a.id}`}
                className="font-medium text-[var(--ink)] hover:text-[var(--accent-ink)]"
              >
                {a.title}
              </Link>
              <div className="flex shrink-0 items-center gap-1">
                {a.type === "area" && <HealthBadge health={a.health} />}
                <EditAreaButton
                  area={{
                    id: a.id,
                    title: a.title,
                    description: a.description,
                    type: a.type,
                    health: a.health,
                  }}
                  iconOnly
                />
              </div>
            </div>
            {a.description && <p className="mt-1 line-clamp-2 text-sm text-[var(--ink-3)]">{a.description}</p>}
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Badge tone="blue">{a._count.projects} projects</Badge>
              <Badge tone="gray">{a._count.tasks} tasks</Badge>
              <Badge tone="gray">{a._count.notes} notes</Badge>
              <Badge tone="gray">{a._count.resources} resources</Badge>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
