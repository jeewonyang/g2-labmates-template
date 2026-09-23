import type { AgentModel } from "./agent-models";
import type { G2AgentRun, G2AgentRunStatus } from "./g2-agent";
import type { MemberState, TeamCard, TeamMemberCard } from "./teams";

/**
 * The Quick Capture coding agent's (Cody's) desk on /teams.
 *
 * It is deliberately NOT a team manifest: it has no producer, no cadence, and
 * no job kinds in the ledger, so giving it a `.claude/agents/teams/*.json`
 * entry would break `teams.py validate`, which asserts every declared kind has
 * a module. It reads its own run files instead. Since 2026-09-22 Cody sits in
 * the Admin room next to Ada (the owner: "move Cody and Ada into same room")
 * rather than in a pod of his own; the pose is still derived from run status,
 * never chosen for looks. Names and roles come from the pod layer's persona
 * map, as with `groupRooms`.
 */

/** The team whose card Cody's desk joins. */
export const CODING_DESK_ROOM = "admin";

export type CodingAgentSummary = {
  running: number;
  queued: number;
  failed: number;
  completed: number;
  lastRun: G2AgentRun | null;
  models: AgentModel[];
};

type Persona = { name: string; role: string };

/**
 * Fold the runs into the desk's numbers.
 *
 * Live and failed counts come from the visible (undismissed) runs - that is the
 * whole point of the Clear control: an acknowledged failure must stop colouring
 * the agent red. "Done" comes from `totals`, the lifetime count over every run
 * file, like the ledger teams' "done" (which reads the whole ledger). She
 * clears finished runs off the monitor, and folding "done" from the visible
 * list left it at 0 however many fixes had landed.
 */
export function summarizeCodingAgent(
  runs: G2AgentRun[],
  models: AgentModel[],
  totals: Record<G2AgentRunStatus, number>,
): CodingAgentSummary {
  const count = (test: (run: G2AgentRun) => boolean) => runs.filter(test).length;
  return {
    running: count((r) => r.status === "running" || r.status === "cancel_requested"),
    queued: count((r) => r.status === "queued"),
    failed: count((r) => r.status === "failed"),
    completed: totals.completed,
    lastRun: runs[0] ?? null,
    models,
  };
}

export function codingAgentStateFor(s: CodingAgentSummary): MemberState {
  // Same precedence as agentStateFor(): the most urgent true thing wins. There
  // is no "needs" state — the coding agent has no approval gate, it leaves its
  // edits unstaged in the working tree.
  if (s.failed > 0) return "alert";
  if (s.running > 0) return "working";
  if (s.queued > 0) return "ready";
  return "idle";
}

function relative(iso: string | null | undefined, now: number): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "never";
  const mins = Math.floor((now - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function lastStamp(run: G2AgentRun | null): string | null {
  return run ? run.finishedAt || run.startedAt || run.createdAt : null;
}

/** Cody as a member desk. `desk: "coding"` is what the pod keys his /ops link on. */
export function codingDeskCard(
  s: CodingAgentSummary,
  persona: Persona,
  now = Date.now(),
): TeamMemberCard {
  let statusNote: string | null = null;
  if (s.failed > 0) statusNote = `${s.failed} failed run${s.failed === 1 ? "" : "s"}`;
  else if (s.running === 0 && s.queued === 0 && s.lastRun) {
    statusNote = `last run ${relative(lastStamp(s.lastRun), now)}`;
  }
  return {
    id: "coding",
    name: persona.name,
    role: persona.role,
    kinds: [],
    desk: "coding",
    queued: s.queued,
    running: s.running,
    needsReview: 0,
    failed: s.failed,
    models: s.models,
    stateOverride: codingAgentStateFor(s),
    statusNote,
  };
}

/**
 * Seat Cody in the Admin room: the admin team becomes Ada's desk, Cody's
 * becomes the second, and the room tallies count both - which is how Cody
 * reaches the /teams floor totals, exactly once. The room's `models` stay the
 * ledger team's so the floor-wide runtime pickers do not pick up Cody's policy
 * kind; his own chip sits on his desk row.
 */
export function withCodingDesk(
  cards: TeamCard[],
  s: CodingAgentSummary,
  personas: { ledger: Persona; coding: Persona },
  now = Date.now(),
): TeamCard[] {
  const cody = codingDeskCard(s, personas.coding, now);
  return cards.map((c) => {
    if (c.id !== CODING_DESK_ROOM) return c;
    const ledgerDesk: TeamMemberCard = {
      id: c.id,
      teamId: c.id,
      name: personas.ledger.name,
      role: personas.ledger.role,
      kinds: c.kinds,
      queued: c.queued,
      running: c.running,
      needsReview: c.needsReview,
      failed: c.failed,
      models: c.models,
      stateOverride: c.cadenceStatus?.overdue ? "alert" : null,
      statusNote: c.cadenceStatus?.overdue ? "run overdue" : null,
    };
    const stamps = [c.lastRunIso, lastStamp(s.lastRun)]
      .filter((t): t is string => Boolean(t))
      .sort();
    return {
      ...c,
      queued: c.queued + s.queued,
      running: c.running + s.running,
      failed: c.failed + s.failed,
      completed: c.completed + s.completed,
      lastRunIso: stamps.length ? stamps[stamps.length - 1] : null,
      memberCards: [...(c.memberCards.length ? c.memberCards : [ledgerDesk]), cody],
    };
  });
}
