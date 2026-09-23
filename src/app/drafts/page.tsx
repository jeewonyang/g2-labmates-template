import { listDrafts } from "@/lib/services/secondbrain";
import { PageHeader, Card, EmptyState } from "@/components/ui/primitives";
import { DraftActions } from "@/components/secondbrain/DraftActions";
import { Mail, MessageSquare } from "lucide-react";
import { AgentCenterNav } from "@/components/layout/SectionNav";
import { DeleteAllDraftsButton } from "@/components/secondbrain/DeleteAllDraftsButton";

export const dynamic = "force-dynamic";

export default async function DraftsPage() {
  const [active, sent] = await Promise.all([
    listDrafts("active"),
    listDrafts("sent"),
  ]);

  return (
    <div>
      <AgentCenterNav />
      <PageHeader
        title="Draft replies"
        subtitle="Review the inferred relationship, edit the reply, and approve or dismiss it. Your category confirmations and tone edits guide future drafts."
        actions={<DeleteAllDraftsButton count={active.length} />}
      />

      {active.length === 0 ? (
        <EmptyState
          title="No drafts waiting"
          description="Incoming email and every new one-to-one Slack DM are drafted automatically after Admin processes them."
        />
      ) : (
        <div className="space-y-4">
          {active.map((d) => (
            <Card key={d.filename} className="p-4">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 text-xs text-[var(--ink-3)]">
                    {d.type === "slack" ? (
                      <MessageSquare className="h-3.5 w-3.5" />
                    ) : (
                      <Mail className="h-3.5 w-3.5" />
                    )}
                    <span className="uppercase tracking-wide">{d.type}</span>
                    {d.created && <span>· {d.created}</span>}
                  </div>
                  <h3 className="mt-1 font-medium text-[var(--ink)]">
                    {d.subject || "(no subject)"}
                  </h3>
                  <p className="text-sm text-[var(--ink-3)]">
                    to {d.recipient || "(unknown)"}
                  </p>
                </div>
              </div>

              {d.context && (
                <p className="mb-3 text-xs italic text-[var(--ink-3)]">
                  {d.context}
                </p>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--ink-3)]">
                    Original
                  </p>
                  <div className="max-h-48 overflow-auto whitespace-pre-wrap rounded-[var(--radius-sm)] bg-[var(--surface-2)] p-3 text-sm text-[var(--ink-2)]">
                    {d.originalMessage || "(none)"}
                  </div>
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--ink-3)]">
                    Draft reply {d.replyEdited ? "· edited by you" : ""}
                  </p>
                  <div className="max-h-48 overflow-auto whitespace-pre-wrap rounded-[var(--radius-sm)] border border-[var(--accent-soft)] bg-[var(--accent-soft)] p-3 text-sm text-[var(--ink)]">
                    {d.draftReply || "(empty)"}
                  </div>
                </div>
              </div>

              <div className="mt-3">
                <DraftActions
                  filename={d.filename}
                  type={d.type}
                  draftReply={d.draftReply}
                  relationshipGroup={d.relationshipGroup}
                  relationshipStatus={d.relationshipStatus}
                  relationshipRationale={d.relationshipRationale}
                  replyEdited={d.replyEdited}
                />
              </div>
            </Card>
          ))}
        </div>
      )}

      {sent.length > 0 && (
        <div className="mt-8">
          <h2 className="mb-2 text-sm font-semibold text-[var(--ink-2)]">
            Recently sent ({sent.length})
          </h2>
          <p className="mb-3 text-xs text-[var(--ink-3)]">
            Replies you handled are kept as the voice-matching corpus.
          </p>
          <ul className="divide-y text-sm">
            {sent.slice(0, 8).map((d) => (
              <li
                key={d.filename}
                className="flex items-center justify-between gap-2 py-2"
              >
                <span className="truncate text-[var(--ink-2)]">
                  {d.subject || d.filename}
                </span>
                <span className="shrink-0 text-xs text-[var(--ink-3)]">
                  to {d.recipient}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
