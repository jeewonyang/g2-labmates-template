import {
  getQueueStats,
  getJob,
  listJobs,
  listNonTriageReviews,
  listReviewBatches,
  listRecentFailures,
} from "@/lib/services/ledger";
import { kindToTeam, teamsForFilter } from "@/lib/services/teams";
import { PageHeader, Card, SectionCard, EmptyState, Stat } from "@/components/ui/primitives";
import { BulkReviewActions } from "@/components/ops/ApproveAllReviews";
import { ReviewBatches } from "@/components/ops/ReviewBatches";
import { ReviewJobs } from "@/components/ops/ReviewJobs";
import { Clock } from "lucide-react";
import { FailureList } from "@/components/ops/FailureList";
import { JobQueue } from "@/components/ops/JobQueue";
import { OpsActionButton } from "@/components/ops/OpsActionButton";
import { AgentCenterNav } from "@/components/layout/SectionNav";
import { listRecentG2AgentRuns } from "@/lib/services/g2-agent";
import { getAutomationDashboard } from "@/lib/services/automation";
import { getHeartbeatStatus } from "@/lib/services/secondbrain";
import { AutomationOverview } from "@/components/automation/AutomationOverview";
import { CodingAgentMonitor } from "@/components/ops/CodingAgentMonitor";

export const dynamic = "force-dynamic";

function relative(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const mins = Math.floor((Date.now() - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default async function OpsPage({
  searchParams,
}: {
  searchParams: Promise<{ team?: string; job?: string; kind?: string }>;
}) {
  const params = await searchParams;
  const [
    stats,
    batches,
    otherReviews,
    failures,
    queued,
    running,
    teamsByKind,
    codingAgentRuns,
    automation,
    heartbeat,
  ] = await Promise.all([
    getQueueStats(),
    listReviewBatches(),
    listNonTriageReviews(),
    listRecentFailures(20),
    listJobs({ status: "created" }),
    listJobs({ status: "claimed" }),
    kindToTeam(),
    listRecentG2AgentRuns(10),
    getAutomationDashboard(),
    getHeartbeatStatus(),
  ]);
  const targetJob = params.job ? await getJob(params.job) : null;
  // A room link (/ops?team=housekeeping) selects every team in the room.
  const teamFilter = params.team ? await teamsForFilter(params.team) : null;
  const visibleJobs = [
    ...(targetJob ? [targetJob] : []),
    ...[...running, ...queued]
      .filter((job) => !teamFilter || teamFilter.has(teamsByKind[job.kind ?? ""] ?? ""))
      .filter((job) => !params.kind || job.kind === params.kind)
      .filter((job) => job.job !== targetJob?.job)
      .slice(-60)
      .reverse(),
  ];

  const pendingReview = batches.reduce((n, b) => n + b.count, 0);
  const totalReviews = pendingReview + otherReviews.length;
  const renderedAt = Date.now();

  /*
    "Approve remaining N": the accept half of a reject-first review pass. The
    eligible set is decided here, on the server, so the button can only approve
    what was on screen at render time.

    Held back on purpose — each of these is an existing per-item rule, not a new
    one:
      - admin.schedule_proposal inserts a Google Calendar event, one of the two
        writes that leave this machine. SOUL.md: they approve the specific item.
      - Confidential destinations, plus the batches listReviewBatches already
        flags requiresPerItem (unclassified, leave-in-inbox, new 10_Projects
        folders).
      - folderMode "create" batches, where approving creates a taxonomy folder
        and re-enqueues rather than filing anything; that decision keeps its own
        clearly-labelled button.
  */
  const approvableJobIds = [
    ...otherReviews
      .filter((job) => job.kind !== "admin.schedule_proposal")
      .map((job) => job.job),
    ...batches
      .filter(
        (batch) =>
          !batch.requiresPerItem &&
          batch.vault !== "Confidential" &&
          batch.folderMode !== "create",
      )
      .flatMap((batch) => batch.jobs.map((job) => job.job)),
  ];
  const heldBackReviews = totalReviews - approvableJobIds.length;

  /*
    "Reject all N": the same render-time snapshot, but nothing is held back.

    Every exclusion above exists because *approving* that item has an effect —
    a file copied into a private vault, a calendar event inserted, a taxonomy
    folder created. Rejecting is the conservative outcome of each of those: the
    capture stays in its inbox, no event exists, no folder is made. It is a
    ledger transition only, the history keeps the declined proposal, and
    apply_jobs.py never sees the job. So withholding a bulk reject would protect
    nothing and would leave a wrong classifier pass as N clicks.
  */
  const rejectableJobIds = [
    ...otherReviews.map((job) => job.job),
    ...batches.flatMap((batch) => batch.jobs.map((job) => job.job)),
  ];

  return (
    <div>
      <AgentCenterNav />
      <PageHeader
        title="Queue & review"
        subtitle="The job ledger: what is queued, what needs you, and what failed. Approving a job files it into the vault — nothing is ever sent."
      />

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Queued" value={String(stats.created)} />
        <Stat label="Running" value={String(stats.claimed)} />
        <Stat label="Needs you" value={String(stats.needsReview)} />
        <Stat label="Failed" value={String(stats.failed)} />
        <Stat label="Done today" value={String(stats.completedToday)} />
        <Stat label="Oldest queued" value={relative(stats.oldestPendingIso)} />
      </div>

      {stats.staleClaims > 0 && (
        <Card className="mb-6 border-amber-400 p-4 dark:border-amber-700">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-3">
            <p className="flex items-center gap-2 text-sm text-amber-800 dark:text-amber-300">
              <Clock className="h-4 w-4" />
              {stats.staleClaims} job
              {stats.staleClaims === 1 ? " has" : "s have"} been claimed for over
              30 minutes — a worker probably died.
            </p>
            <OpsActionButton
              action="reap"
              label="Requeue them"
              busyLabel="Requeuing…"
              title="Return abandoned claims to the queue (dispatch.py --reap)"
            />
          </div>
        </Card>
      )}

      {/*
        Moved off /today on 2026-08-01. This is the page whose job is the
        queue, so the metric grid and recent-capture rows belong here; /today
        keeps only the run controls and a "N waiting on your decision" link.
      */}
      <SectionCard title="Capture automation" className="mb-6">
        <AutomationOverview
          data={{
            active: automation.active,
            needsAttention: automation.needsAttention,
            appliedRecently: automation.appliedRecently,
            windowDays: automation.recentWindowDays,
            failed: automation.counts.failed ?? 0,
            reviewQueue: stats.needsReview,
            heartbeatLastRun: heartbeat.lastRun,
            recent: automation.recent.map((row) => ({
              id: row.id,
              state: row.state,
              confidence: row.confidence,
              title:
                row.inboxItem.parsedTitle || row.inboxItem.rawText.slice(0, 100),
            })),
          }}
        />
      </SectionCard>

      <SectionCard
        title={`Queued & running work (${visibleJobs.length})`}
        className="mb-6"
        action={
          stats.created > 0 ? (
            <OpsActionButton
              action="drain"
              label={`Run ${stats.created} queued now`}
              busyLabel="Starting…"
              title="Dispatch queued jobs immediately instead of waiting for the next scheduled run. Anything needing approval still stops for your decision."
            />
          ) : undefined
        }
      >
        {params.team && (
          <p className="mb-3 text-xs text-[var(--ink-3)]">
            Showing the {params.team} team.{" "}
            <a href="/ops" className="text-[var(--accent-ink)] hover:underline">
              Clear filter
            </a>
          </p>
        )}
        {params.kind && (
          <p className="mb-3 text-xs text-[var(--ink-3)]">
            Showing <span className="font-mono">{params.kind}</span>.{" "}
            <a href="/ops" className="text-[var(--accent-ink)] hover:underline">
              Clear filter
            </a>
          </p>
        )}
        {visibleJobs.length === 0 ? (
          <EmptyState
            title="Nothing queued"
            description="Deploying agents or capturing new material will add work here."
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-[var(--ink-3)]">
              Click any row to see exactly what the agent received, which
              runtime will handle it, and its current state.
            </p>
            <JobQueue
              jobs={visibleJobs}
              initialJob={params.job}
              renderedAt={renderedAt}
              queuedSlackDraftJobIds={queued
                .filter((job) => job.kind === "draft.reply")
                .map((job) => job.job)}
            />
          </>
        )}
      </SectionCard>

      <SectionCard
        title="Coding agent monitor"
        className="mb-6"
      >
        <CodingAgentMonitor initialRuns={codingAgentRuns} />
      </SectionCard>

      <SectionCard
        title="Needs your review"
        className="mb-6"
        action={
          approvableJobIds.length > 1 || rejectableJobIds.length > 1 ? (
            <BulkReviewActions
              approvableJobIds={approvableJobIds}
              rejectableJobIds={rejectableJobIds}
              heldBack={heldBackReviews}
            />
          ) : undefined
        }
      >
        {totalReviews === 0 ? (
          <EmptyState
            title="Nothing waiting"
            description="Classifications and other agent proposals that need a decision will appear here."
          />
        ) : (
          <div className="space-y-5">
            {approvableJobIds.length > 1 && heldBackReviews > 0 && (
              // The buttons' tooltips say this too, but they read /ops on an
              // tablet, where there is no hover.
              <p className="text-xs text-[var(--ink-3)]">
                &ldquo;Approve remaining&rdquo; leaves {heldBackReviews} item
                {heldBackReviews === 1 ? "" : "s"} alone — calendar proposals,
                confidential destinations, and new folders stay individual
                decisions. &ldquo;Reject all&rdquo; covers them too: declining
                files nothing and deletes nothing.
              </p>
            )}
            {otherReviews.length > 0 && (
              <div>
                <p className="mb-3 text-sm text-[var(--ink-3)]">
                  {otherReviews.length} agent proposal
                  {otherReviews.length === 1 ? "" : "s"} awaiting a decision.
                  Expand a proposal to review its findings and recommended action.
                </p>
                <ReviewJobs jobs={otherReviews} />
              </div>
            )}
            {pendingReview > 0 && (
              <div>
                <p className="mb-3 text-sm text-[var(--ink-3)]">
                  {pendingReview} classified file{pendingReview === 1 ? "" : "s"} in{" "}
                  {batches.length} destination{batches.length === 1 ? "" : "s"}.
                </p>
                <ReviewBatches batches={batches} />
              </div>
            )}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Recent failures" className="mb-6">
        {failures.length === 0 ? (
          <EmptyState title="No failures" description="Nothing has errored." />
        ) : (
          <FailureList failures={failures} />
        )}
      </SectionCard>
      {/*
        The "Cost" card was dropped 2026-08-27: it rendered a sentence about
        routing and no numbers — the fetched usage summary was only a
        visibility gate. Subscription capacity lives in the header usage board.
      */}
    </div>
  );
}
