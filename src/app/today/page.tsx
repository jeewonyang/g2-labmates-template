import Link from "next/link";
import { format } from "date-fns";
import {
  AlertCircle,
  CalendarClock,
  CalendarDays,
  CalendarRange,
  ChevronRight,
  Mail,
  Star,
} from "lucide-react";
import {
  countPullableOverdueTasks,
  countTriageTasks,
  getTodayTasks,
  getUpcomingTasks,
  getWeekTasks,
  listTasks,
} from "@/lib/services/tasks";
import { getProjectsNeedingAttention } from "@/lib/services/projects";
import { getDailyNote } from "@/lib/services/notes";
import { getWeeklyReviewStatus } from "@/lib/services/reviews";
import { formatDateInput } from "@/lib/utils";
import { listAreas } from "@/lib/services/areas";
import { listProjects } from "@/lib/services/projects";
import { EmptyState } from "@/components/ui/primitives";
import { CollapsibleSectionCard } from "@/components/ui/CollapsibleCard";
import { TaskList } from "@/components/tasks/TaskItem";
import { PullOverdueButton } from "@/components/tasks/PullOverdueButton";
import { DailyNoteEditor } from "@/components/notes/DailyNoteEditor";
import { NewTaskButton } from "@/components/forms/CreateForms";
import { listDrafts } from "@/lib/services/secondbrain";
import {
  DraftsPanelFooter,
  InboxDraftsPanel,
} from "@/components/home/InboxDraftsPanel";
import { ExecutiveDigestPanel } from "@/components/home/ExecutiveDigestPanel";
import { WeekCalendar } from "@/components/home/WeekCalendar";
import { UpcomingList } from "@/components/home/UpcomingList";
import {
  DayScheduleBoard,
  RegenerateDayPlanButton,
} from "@/components/home/DaySchedulePanel";
import { getDayPlanBoard } from "@/lib/services/dayPlan";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  const now = new Date();
  const [
    todayTasks,
    weekTasks,
    upcoming,
    needsAttention,
    dailyNote,
    weeklyReview,
    projects,
    areas,
    drafts,
    overdueCount,
    triageTasks,
    triageCount,
    dayPlanBoard,
  ] =
    await Promise.all([
      getTodayTasks(now),
      getWeekTasks(now),
      getUpcomingTasks(14, now),
      getProjectsNeedingAttention(),
      getDailyNote(now),
      getWeeklyReviewStatus(now),
      listProjects(),
      listAreas(),
      listDrafts("active"),
      countPullableOverdueTasks(now),
      listTasks({ view: "triage" }),
      countTriageTasks(),
      getDayPlanBoard(now),
    ]);

  const highlights = todayTasks.filter((t) => t.isHighlight);
  // The highlight also stays in "Due & scheduled" (the owner, 2026-09-21):
  // getTodayTasks() already orders it first, then by priority.
  const dueToday = todayTasks;
  const projectOptions = projects.map((p) => ({
    id: p.id,
    title: p.title,
    areaId: p.areaId,
  }));
  const areaOptions = areas.map((a) => ({ id: a.id, title: a.title }));

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-[var(--accent-ink)]">{format(now, "EEEE")}</p>
          <h1 className="text-2xl font-bold tracking-tight text-[var(--ink)]">
            {format(now, "MMMM d, yyyy")}
          </h1>
        </div>
        <NewTaskButton projects={projectOptions} areas={areaOptions} />
      </div>

      <div className="mb-4">
        <ExecutiveDigestPanel />
      </div>

      {/*
        Research Newsletters moved to /research/feeds on 2026-08-27 (the owner:
        research gets its own space). The CEO Brief above still carries the
        research digests that need their attention on the daily surface.
      */}

      {/*
        Highlight and the week strip are one card. They answer the same
        question — what today looks like against the rest of the week — and
        splitting them put a card boundary between the starred task and the day
        it sits on.
      */}
      <CollapsibleSectionCard
        storageKey="today-week"
        title={
          <span className="flex items-center gap-1.5">
            <CalendarRange className="h-4 w-4 text-[var(--ink-3)]" />
            Today&apos;s highlight &amp; this week
          </span>
        }
        action={
          <Link
            href="/tasks?view=upcoming"
            className="text-xs text-[var(--accent-ink)] hover:underline"
          >
            All tasks
          </Link>
        }
        className="mb-4"
      >
        <div className="mb-3 rounded-[var(--radius-sm)] border bg-[var(--surface-2)] px-3 py-1.5">
          <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--ink-3)]">
            <Star className="h-3 w-3 text-[var(--amber)]" fill="currentColor" />
            Highlight
          </div>
          {highlights.length ? (
            <TaskList tasks={highlights} showHighlight={false} />
          ) : (
            <p className="py-1.5 text-sm text-[var(--ink-3)]">
              No highlight set. Star a task to mark the one thing that matters most today.
            </p>
          )}
        </div>
        <WeekCalendar
          tasks={weekTasks}
          triage={triageTasks.slice(0, 8)}
          triageTotal={triageCount}
          now={now}
          projects={projectOptions}
          areas={areaOptions}
        />
        {/*
          The weekly review lives at the foot of the week strip because that is
          where the week is already in view. Reviews had no inbound link from
          the daily surface at all, so it was a page they had to remember.
        */}
        <div className="mt-3 flex items-center justify-between gap-2 border-t pt-2 text-xs">
          <span className="text-[var(--ink-3)]">
            {weeklyReview.done
              ? "Weekly review done for this week."
              : "No weekly review for this week yet."}
          </span>
          <Link
            href={`/reviews?type=weekly&date=${formatDateInput(now)}`}
            className="text-[var(--accent-ink)] hover:underline"
          >
            {weeklyReview.done ? "Open review" : "Write it"}
          </Link>
        </div>
      </CollapsibleSectionCard>

      {/*
        The suggested schedule sits directly under the week strip (the owner,
        2026-09-16): the week says what is due, this says when today it gets
        done. Fixed blocks come from .claude/agents/day-schedule.json; the
        tasks are today's open ones with durations inferred from their content.
        The plan is stored at generation time so the board does not reshuffle
        as they read it - Regenerate is how tasks captured after waking get
        placed.
      */}
      <CollapsibleSectionCard
        storageKey="today-schedule"
        title={
          <span className="flex items-center gap-1.5">
            <CalendarClock className="h-4 w-4 text-[var(--ink-3)]" />
            Plan &amp; actual
            {dayPlanBoard.newSince.length > 0 && (
              <span className="rounded-full bg-[var(--amber-soft)] px-1.5 text-[11px] font-semibold text-[var(--amber)]">
                {dayPlanBoard.newSince.length} new
              </span>
            )}
          </span>
        }
        action={<RegenerateDayPlanButton generatedAt={dayPlanBoard.plan.generatedAt} />}
        className="mb-4"
      >
        <DayScheduleBoard board={dayPlanBoard} />
      </CollapsibleSectionCard>

      {/*
        items-start stops the two columns being stretched to a common height.
        They hold different amounts of content, so stretching left ~900px of
        dead space under the right rail — the ragged bottom edge that made the
        page look unfinished. The rail is then pinned so it stays in view while
        the longer column scrolls, with its own overflow guard for the days the
        rail grows taller than the viewport.
      */}
      <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-3">
        <div className="min-w-0 space-y-4 lg:col-span-2">
          {/* Due / scheduled today */}
          <CollapsibleSectionCard
            storageKey="today-due"
            title={`Due & scheduled (${dueToday.length})`}
            action={<PullOverdueButton count={overdueCount} />}
          >
            {dueToday.length ? (
              <TaskList tasks={dueToday} />
            ) : (
              <EmptyState title="Nothing due today" description="You're clear. Pull something from Upcoming or capture a new task." />
            )}
          </CollapsibleSectionCard>

          <CollapsibleSectionCard
            storageKey="today-drafts"
            title={
              <span className="flex items-center gap-1.5">
                <Mail className="h-4 w-4 text-[var(--ink-3)]" />
                Messages &amp; drafts
                {drafts.length > 0 && (
                  <span className="rounded-full bg-[var(--amber-soft)] px-1.5 text-[11px] font-semibold text-[var(--amber)]">
                    {drafts.length}
                  </span>
                )}
              </span>
            }
            action={<DraftsPanelFooter count={drafts.length} />}
          >
            <InboxDraftsPanel
              drafts={drafts.map((d) => ({
                filename: d.filename,
                type: d.type,
                recipient: d.recipient,
                subject: d.subject,
                context: d.context,
                created: d.created,
                originalMessage: d.originalMessage,
                draftReply: d.draftReply,
              }))}
            />
          </CollapsibleSectionCard>
          {/*
            "Needs you" was removed 2026-08-27 (the owner: never used it). The
            run controls and the decision count live on /ops, and the Agent
            Center badge in the sidebar already carries the waiting count.
          */}

          {/* Projects needing attention */}
          <CollapsibleSectionCard
            storageKey="today-projects"
            title="Projects needing attention"
            action={<Link href="/projects" className="text-xs text-[var(--accent-ink)] hover:underline">All projects</Link>}
          >
            {needsAttention.length ? (
              <ul className="divide-y">
                {needsAttention.map((p) => (
                  <li key={p.id}>
                    <Link href={`/projects/${p.id}`} className="flex items-center gap-3 py-2.5 hover:opacity-80">
                      <AlertCircle className="h-4 w-4 shrink-0 text-[var(--amber)]" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-[var(--ink)]">{p.title}</div>
                        <div className="text-xs text-[var(--ink-3)]">No open next action</div>
                      </div>
                      <ChevronRight className="h-4 w-4 text-[var(--ink-3)]" />
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--ink-3)]">Every active project has a next action. Nice.</p>
            )}
          </CollapsibleSectionCard>
        </div>

        {/* Sidebar column */}
        <div className="min-w-0 space-y-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
          {/*
            Upcoming leads the rail so it sits shoulder-to-shoulder with "Due &
            scheduled" at the top of the main column: what is due now and what
            is coming are one question read across, not two stacked apart.
          */}
          <CollapsibleSectionCard
            storageKey="today-upcoming"
            title={
              <span className="flex items-center gap-1.5">
                <CalendarDays className="h-4 w-4 text-[var(--ink-3)]" />
                Upcoming (14 days)
              </span>
            }
          >
            {upcoming.length ? (
              <UpcomingList tasks={upcoming.slice(0, 8)} />
            ) : (
              <p className="text-sm text-[var(--ink-3)]">Nothing scheduled in the next two weeks.</p>
            )}
          </CollapsibleSectionCard>

          <CollapsibleSectionCard storageKey="today-daily-note" title="Daily note">
            <DailyNoteEditor initialContent={dailyNote?.contentMarkdown ?? ""} />
          </CollapsibleSectionCard>

        </div>
      </div>
    </div>
  );
}

