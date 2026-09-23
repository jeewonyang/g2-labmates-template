import { listInboxItems } from "@/lib/services/capture";
import { PlannerNav } from "@/components/layout/SectionNav";
import { listOrganizedCaptures } from "@/lib/services/automation";
import { PageHeader } from "@/components/ui/primitives";
import { InboxTriage } from "@/components/inbox/InboxTriage";
import { OrganizedCaptures } from "@/components/inbox/OrganizedCaptures";

export const dynamic = "force-dynamic";

export default async function InboxPage() {
  const [items, organized] = await Promise.all([
    listInboxItems("inbox"),
    listOrganizedCaptures(),
  ]);

  return (
    <div>
      <PlannerNav />
      <PageHeader
        title="Inbox"
        subtitle="Everything you captured, from anywhere. Triage each item into a task, note, or resource."
      />
      <InboxTriage
        items={items.map((i) => ({
          id: i.id,
          rawText: i.rawText,
          parsedTitle: i.parsedTitle,
          type: i.type,
          source: i.source,
          sourceUrl: i.sourceUrl,
          capturedAt: i.capturedAt,
          tags: i.tags.map((t) => ({ id: t.id, name: t.name })),
          automation: i.automation
            ? {
                state: i.automation.state,
                confidence: i.automation.confidence,
                destinationPath: i.automation.destinationPath,
                error: i.automation.error,
              }
            : null,
        }))}
      />
      <OrganizedCaptures
        items={organized.map((o) => ({
          ...o,
          completedAt: o.completedAt.toISOString(),
        }))}
      />
    </div>
  );
}
