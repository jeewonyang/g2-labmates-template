import { formatDistanceToNow } from "date-fns";
import { Check, AlertTriangle, Minus } from "lucide-react";
import { db } from "@/lib/db";
import { PageHeader, SectionCard, Stat } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/Badge";
import { CAPTURE_SOURCES } from "@/lib/types";
import { getDeploymentStatus } from "@/lib/services/deployment";
import {
  getSetupReport,
  GROUP_LABEL,
  type SetupGroup,
  type SetupItem,
} from "@/lib/services/setup";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const [setup, deployment, projects, tasks, notes, resources, areas, goals, inbox, reviews, tags] =
    await Promise.all([
      getSetupReport(),
      getDeploymentStatus(),
      db.project.count(),
      db.task.count(),
      db.note.count(),
      db.resource.count(),
      db.area.count(),
      db.goal.count(),
      db.inboxItem.count(),
      db.review.count(),
      db.tag.count(),
    ]);

  return (
    <div>
      <PageHeader title="About & diagnostics" subtitle="Setup status, workspace health, capture API, and keyboard shortcuts." />

      <SectionCard title="Setup checklist" className="mb-6" bodyClassName="p-0">
        <div>
          <p className="border-b border-[var(--border)] px-4 py-2.5 text-sm text-[var(--ink-2)]">
            {setup.ready
              ? setup.agentCapable
                ? "Nothing needs attention. Agent automation is available on this machine; optional rows switch on when their tokens appear."
                : "Nothing needs attention. No AI subscription is linked, so everything runs manually — link Claude or ChatGPT (Codex) below whenever you want agent automation."
              : `${setup.attention} item${setup.attention === 1 ? "" : "s"} need${setup.attention === 1 ? "s" : ""} attention.`}
            {" "}Every row is verified live against this machine — nothing is asserted from config.
            {" "}<span className="text-[var(--ink-3)]">
              To use a <span className="font-mono text-[11px] uppercase">run</span> fix: open a
              terminal in this folder (Windows: open the folder, type <code>powershell</code> in
              File Explorer&apos;s address bar, press Enter), paste the command, press Enter. To use
              an <span className="font-mono text-[11px] uppercase">ask G2</span> fix: in that same
              terminal type <code>claude</code>, press Enter, then paste the message — the agent
              does the technical part for you.
            </span>
          </p>
          {(Object.keys(GROUP_LABEL) as SetupGroup[]).map((group) => (
            <div key={group}>
              <div className="border-b border-[var(--border)] bg-[var(--surface-2)]/50 px-4 py-1.5">
                <span className="font-mono text-[10px] uppercase tracking-wide text-[var(--ink-3)]">
                  {GROUP_LABEL[group].title}
                </span>
                <span className="ml-2 text-xs text-[var(--ink-3)]">{GROUP_LABEL[group].blurb}</span>
              </div>
              {setup.items
                .filter((item) => item.group === group)
                .map((item) => (
                  <SetupRow key={item.id} item={item} />
                ))}
            </div>
          ))}
        </div>
      </SectionCard>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Projects" value={projects} />
        <Stat label="Tasks" value={tasks} />
        <Stat label="Notes" value={notes} />
        <Stat label="Resources" value={resources} />
        <Stat label="Areas" value={areas} />
        <Stat label="Goals" value={goals} />
        <Stat label="Reviews" value={reviews} />
        <Stat label="Tags" value={tags} />
      </div>

      {/*
        Deployment. The question this answers is "is this machine running the
        change I just made?" - the one thing no surface could say when a change
        pushed from a laptop or a cloud session did not show up here. It
        reports only what it can read locally: the commit this server is on, and
        the updater's last checkpoint. It never fetches (a page render must not
        wait on the network) and never claims the auto-update task is
        registered, because from here that cannot be verified.
      */}
      <div className="mb-4">
        <SectionCard title="Deployment">
          {deployment.error ? (
            <p className="text-sm text-[var(--ink-3)]">{deployment.error}</p>
          ) : (
            <div className="space-y-2 text-sm">
              <Row
                label="Running"
                value={
                  <span className="text-right">
                    <code className="text-xs">{deployment.commit}</code>
                    {deployment.branch && (
                      <span className="text-[var(--ink-3)]"> on {deployment.branch}</span>
                    )}
                  </span>
                }
              />
              {deployment.subject && (
                <Row
                  label="Last commit"
                  value={
                    <span className="text-right">
                      {deployment.subject}
                      {deployment.committedAt && (
                        <span className="text-[var(--ink-3)]">
                          {" · "}
                          {formatDistanceToNow(new Date(deployment.committedAt), { addSuffix: true })}
                        </span>
                      )}
                    </span>
                  }
                />
              )}
              {deployment.dirtyFiles ? (
                <p className="text-xs text-[var(--amber)]">
                  {deployment.dirtyFiles} tracked file
                  {deployment.dirtyFiles === 1 ? " has" : "s have"} uncommitted changes here, so
                  automatic updates are skipped until they are committed or reverted. Nothing is
                  discarded.
                </p>
              ) : null}
              {deployment.lastCheck ? (
                <Row
                  label="Last update check"
                  value={
                    <span className="text-right text-[var(--ink-2)]">
                      {deployment.lastCheck.at}
                      <span className="text-[var(--ink-3)]"> · {deployment.lastCheck.message}</span>
                    </span>
                  }
                />
              ) : deployment.updaterHasNeverRun ? (
                <p className="text-xs text-[var(--ink-3)]">
                  The updater has never run on this machine. Register it with
                  <code className="mx-1 text-xs">.claude\scripts\setup_web_host.ps1</code>, or update
                  by hand with <code className="mx-1 text-xs">update-g2.bat</code>.
                </p>
              ) : null}
              <p className="text-xs text-[var(--ink-3)]">
                Pushing is not deploying: this machine has to fast-forward and re-register the
                scheduled tasks, which store a snapshot of the day schedule rather than reading it.
                <code className="mx-1 text-xs">update-g2.bat -Status</code> reports both.
              </p>
            </div>
          )}
        </SectionCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/*
          Month-to-date API spend used to sit here. It was replaced by the
          header usage board, which tracks what actually constrains the work -
          remaining Claude/Codex subscription capacity and time to reset. The
          usage.jsonl ledger keeps recording; only this card went away.
        */}
        <SectionCard title="Capture API">
          <p className="text-sm text-[var(--ink-2)]">
            The capture API is the stable boundary a future iOS app, widget, Share Sheet, or Siri
            Shortcut will use to add items to your inbox. {inbox} item{inbox === 1 ? "" : "s"} captured so far.
          </p>
          <div className="mt-3 space-y-2 text-sm">
            <Row label="Create endpoint" value={<code className="text-xs">POST /api/capture</code>} />
            <Row label="Batch sync" value={<code className="text-xs">POST /api/capture/batch</code>} />
            <Row label="Auth" value="Bearer token (CAPTURE_API_TOKEN)" />
          </div>
          <p className="mt-3 text-xs text-[var(--ink-3)]">
            Full contract and iOS integration guide: <code>docs/CAPTURE_API.md</code>.
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {CAPTURE_SOURCES.map((s) => <Badge key={s} tone="gray">{s}</Badge>)}
          </div>
        </SectionCard>

        <SectionCard title="Keyboard shortcuts">
          <dl className="space-y-2 text-sm">
            <Shortcut keys="⌘ / Ctrl + K" label="Command palette & search" />
            <Shortcut keys="c" label="Quick capture" />
            <Shortcut keys="⌘/Ctrl + Shift + Space" label="Quick capture (global)" />
            <Shortcut keys="g then t" label="Go to Today" />
            <Shortcut keys="g then i" label="Go to Inbox" />
            <Shortcut keys="g then p" label="Go to Projects" />
            <Shortcut keys="g then k" label="Go to Tasks" />
            <Shortcut keys="g then a / x / v" label="Areas / Archive / Reviews" />
            <Shortcut keys="g then r / e / w / s" label="Research / Teams / Wiki / Diagnostics" />
          </dl>
        </SectionCard>

        <SectionCard title="Data model">
          <p className="text-sm text-[var(--ink-2)]">
            Status, type, and priority fields are stored as plain strings and defined in
            <code className="mx-1 text-xs">src/lib/types.ts</code>, so you can rename sections or add
            new object types without a database migration. Relations are typed in
            <code className="mx-1 text-xs">prisma/schema.prisma</code>.
          </p>
        </SectionCard>

        <SectionCard title="About">
          <p className="text-sm text-[var(--ink-2)]">
            A web-based Second Brain modeled on your Notion system (수집 · 명료화 · 계획 · 점검), built with
            Next.js, Prisma, and SQLite. Business logic is isolated in
            <code className="mx-1 text-xs">src/lib/services</code> so the same core powers both the web
            UI and the capture API.
          </p>
        </SectionCard>
      </div>
    </div>
  );
}

function SetupRow({ item }: { item: SetupItem }) {
  const icon =
    item.state === "ok" ? (
      <Check size={12} className="text-[var(--cyan)]" />
    ) : item.state === "attention" ? (
      <AlertTriangle size={12} className="text-[var(--amber)]" />
    ) : (
      <Minus size={12} className="text-[var(--ink-3)]" />
    );
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-[var(--border)] px-4 py-2.5 last:border-b-0">
      <span className="flex min-w-56 items-center gap-2 text-sm font-medium text-[var(--ink)]">
        {icon}
        {item.label}
      </span>
      <span className="flex-1 basis-64 text-[13px] text-[var(--ink-2)]">
        {item.detail}
        {item.fix && (
          <span className="mt-1 flex items-baseline gap-1.5">
            <span className="shrink-0 rounded bg-[var(--surface-2)] px-1 py-0.5 font-mono text-[10px] uppercase tracking-wide text-[var(--ink-3)]">
              {item.fix.kind === "run" ? "run" : "ask G2"}
            </span>
            <code className="rounded bg-[var(--surface-2)] px-1 py-0.5 text-xs text-[var(--ink-2)]">
              {item.fix.text}
            </code>
          </span>
        )}
      </span>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[var(--ink-3)]">{label}</span>
      <span className="text-[var(--ink)]">{value}</span>
    </div>
  );
}

function Shortcut({ keys, label }: { keys: string; label: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-[var(--ink-2)]">{label}</dt>
      <dd><kbd className="rounded border bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-xs text-[var(--ink-2)]">{keys}</kbd></dd>
    </div>
  );
}
