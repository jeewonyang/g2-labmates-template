import Link from "next/link";
import { groupRooms, listTeamCards } from "@/lib/services/teams";
import { PageHeader, SectionCard, EmptyState } from "@/components/ui/primitives";
import {
  TeamPod,
  agentStateFor,
  memberStateFor,
  AGENT_NAMES,
  AGENT_ROLES,
  DESK_ROLES,
} from "@/components/teams/TeamPod";
import { PixelAgent, type AgentState } from "@/components/teams/PixelAgent";
import { DeployAllAgents } from "@/components/teams/DeployAllAgents";
import { AgentCenterNav } from "@/components/layout/SectionNav";
import { summarizeCodingAgent, withCodingDesk } from "@/lib/services/coding-desk";
import { countG2AgentRuns, listRecentG2AgentRuns } from "@/lib/services/g2-agent";
import { codingAgentModels, listModelChoices, readModelPolicy } from "@/lib/services/agent-models";
import { isModelRuntime, type ModelRuntime } from "@/lib/agent-model-choices";
import { ModelPicker } from "@/components/teams/ModelPicker";

export const dynamic = "force-dynamic";

const LEGEND: Array<{ state: AgentState; label: string; meaning: string }> = [
  { state: "needs", label: "Waving", meaning: "waiting on your approval" },
  { state: "working", label: "Typing", meaning: "a job is running now" },
  { state: "ready", label: "At the desk", meaning: "work queued, not started" },
  { state: "idle", label: "Asleep", meaning: "nothing to do" },
  { state: "alert", label: "Flailing", meaning: "a job failed" },
];

export default async function TeamsPage() {
  const [cards, codingRuns, codingTotals, codingModels, policy, modelChoices] = await Promise.all([
    listTeamCards(),
    listRecentG2AgentRuns(10),
    countG2AgentRuns(),
    codingAgentModels(),
    readModelPolicy(),
    listModelChoices(),
  ]);
  // Teams that share a room (vault + security = Housekeeping) render as one
  // card with a desk per team. Cody, who is not a manifest team, joins the
  // Admin room as Ada's desk-mate (2026-09-22); his tallies count in the
  // room's, so the floor totals below include him once.
  const coding = summarizeCodingAgent(codingRuns, codingModels, codingTotals);
  const teams = withCodingDesk(
    groupRooms(cards, (id) => ({
      name: AGENT_NAMES[id] ?? id,
      role: AGENT_ROLES[id] ?? "",
    })),
    coding,
    {
      ledger: { name: AGENT_NAMES.admin, role: DESK_ROLES.admin },
      coding: { name: AGENT_NAMES.coding, role: AGENT_ROLES.coding },
    },
  );
  const modelDefaults: Partial<Record<string, string | null>> = {
    claude: policy.defaults.claude ?? null,
    codex: policy.defaults.codex ?? null,
    ollama: policy.defaults.ollama ?? null,
  };
  // Every kind on the floor grouped by runtime, for the runtime-wide pickers.
  const kindsByRuntime = new Map<ModelRuntime, string[]>();
  for (const t of teams) {
    for (const m of t.models) {
      if (!isModelRuntime(m.runtime)) continue;
      kindsByRuntime.set(m.runtime, [...(kindsByRuntime.get(m.runtime) ?? []), ...m.kinds]);
    }
  }
  const runtimeRows = (["claude", "codex", "ollama"] as const)
    .filter((r) => (kindsByRuntime.get(r) ?? []).length > 0)
    .map((runtime) => ({
      runtime,
      model: modelDefaults[runtime] ?? "as coded",
      kinds: kindsByRuntime.get(runtime) ?? [],
      pinned: Boolean(modelDefaults[runtime]),
      coded: null,
    }));
  // The coding agent counts toward the floor totals (through the Admin room's
  // tallies). It edits the working tree, so a failure there matters at least
  // as much as a failed ledger job — the header would be lying if it said
  // "0 failed" while Cody was flailing.
  const totals = teams.reduce(
    (acc, t) => ({
      needsReview: acc.needsReview + t.needsReview,
      queued: acc.queued + t.queued,
      running: acc.running + t.running,
      failed: acc.failed + t.failed,
    }),
    { needsReview: 0, queued: 0, running: 0, failed: 0 },
  );

  // One honest sentence about the whole floor, in priority order.
  const awake = teams.filter((t) => agentStateFor(t) !== "idle");
  const waving = teams.filter((t) => agentStateFor(t) === "needs");
  const brokenNames = [
    // Name the specific member when a desk inside a team is the alert (a
    // failed lab run) — the team's ledger tallies can be clean while one desk
    // is not.
    ...teams.flatMap((t) => {
      const memberAlerts = t.memberCards
        .filter((m) => memberStateFor(m) === "alert")
        .map((m) => m.name);
      if (memberAlerts.length > 0) return memberAlerts;
      return agentStateFor(t) === "alert" ? [AGENT_NAMES[t.id] ?? t.id] : [];
    }),
  ];

  let mood: string;
  if (brokenNames.length > 0) {
    // A desk can be in alert without a ledger failure (a failed lab run) —
    // "hit 0 failures" would be nonsense.
    mood = totals.failed > 0
      ? `${brokenNames.join(" and ")} hit ${totals.failed} failure${totals.failed === 1 ? "" : "s"} — worth a look.`
      : `${brokenNames.join(" and ")} need${brokenNames.length === 1 ? "s" : ""} a hand — worth a look.`;
  } else if (waving.length > 0) {
    mood = `${waving.map((t) => AGENT_NAMES[t.id] ?? t.id).join(", ")} ${
      waving.length === 1 ? "is" : "are"
    } waving: ${totals.needsReview} item${
      totals.needsReview === 1 ? "" : "s"
    } waiting on you.`;
  } else if (totals.running > 0) {
    mood = `${totals.running} job${totals.running === 1 ? "" : "s"} running. Nothing needs you.`;
  } else if (awake.length === 0) {
    mood = "Whole floor is asleep. Nothing queued, nothing waiting.";
  } else {
    mood = "All caught up — work queued but nothing needs you.";
  }

  return (
    <div>
      <AgentCenterNav />
      <PageHeader
        title="The Office"
        actions={<DeployAllAgents />}
        subtitle={`${teams.length} rooms, one shared job ledger. They draft, digest, and audit — approving is always yours.`}
      />

      {teams.length === 0 ? (
        <EmptyState
          title="Nobody's clocked in"
          description="Team manifests live in .claude/agents/teams/*.json. Run `python .claude/scripts/teams.py validate` to check them."
        />
      ) : (
        <>
          {/* Floor status: one sentence, then the legend. */}
          <div className="mb-5 overflow-hidden rounded-[var(--radius-card)] border border-[var(--border)] bg-[var(--surface)]">
            <div className="office-wall flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <p className="text-sm text-[var(--ink)]">{mood}</p>
              <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-wide text-[var(--ink-3)]">
                <span>
                  <span className="text-[var(--amber)]">{totals.needsReview}</span>{" "}
                  needs you
                </span>
                <span>
                  <span className="text-[var(--cyan)]">{totals.queued}</span> queued
                </span>
                <span>
                  <span className="text-[var(--red)]">{totals.failed}</span> failed
                </span>
              </div>
            </div>

            {runtimeRows.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] px-4 py-2 text-[11px] text-[var(--ink-2)]">
                <span>Default model for every desk, per runtime:</span>
                <ModelPicker scope="all" models={runtimeRows} choices={modelChoices} />
                <span className="text-[var(--ink-3)]">
                  A desk&apos;s own pick wins over this. A spent Fable or Opus window still steps down
                  (Fable → Opus → Sonnet) on its own.
                </span>
              </div>
            )}

            <div className="office-floor flex flex-wrap gap-x-5 gap-y-2 border-t border-[var(--border)] px-4 py-2.5">
              {LEGEND.map((l) => (
                <div key={l.state} className="flex items-center gap-1.5">
                  <PixelAgent
                    team="legend"
                    state={l.state}
                    size={26}
                    title={l.label}
                  />
                  <span className="text-[11px] text-[var(--ink-2)]">
                    <span className="font-medium text-[var(--ink)]">{l.label}</span>
                    <span className="text-[var(--ink-3)]"> — {l.meaning}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* The floor itself. Cody has a desk here, not just a panel on /ops
              — since 2026-09-22 in the Admin room beside Ada. */}
          <div className="grid gap-4 lg:grid-cols-2">
            {teams.map((t) => (
              <TeamPod key={t.id} team={t} modelDefaults={modelDefaults} modelChoices={modelChoices} />
            ))}
          </div>

          {/*
            Cody's run list was dropped from this page 2026-08-27: it rendered
            the same CodingAgentMonitor /ops already shows, and his desk above
            carries his status. /teams is the status floor; run detail is an
            /ops concern.
          */}
          <SectionCard title="How the office works" className="mt-6">
            <p className="text-sm text-[var(--ink-3)]">
              Each agent owns a set of job kinds. A producer decides what work
              exists, then everything runs through the same ledger and the same
              approval gate you see on{" "}
              <Link href="/ops" className="underline">
                Agent OS
              </Link>
              . Anything that would reach outside{" "}
              <code className="rounded bg-[var(--surface-2)] px-1">
                VAULT/Memory/
              </code>{" "}
              waits for you first — the poses above are read from the ledger, so
              a waving agent always means real work is pending.
            </p>
            <p className="mt-2 text-sm text-[var(--ink-3)]">
              Run everyone due today with{" "}
              <code className="rounded bg-[var(--surface-2)] px-1">
                python .claude/scripts/agent_day.py
              </code>
              , or one with{" "}
              <code className="rounded bg-[var(--surface-2)] px-1">
                --team &lt;id&gt;
              </code>
              . A lock icon means that agent only ever uses local models.
            </p>
          </SectionCard>
        </>
      )}
    </div>
  );
}
