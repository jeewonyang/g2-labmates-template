import Link from "next/link";
import type { ReactNode } from "react";
import type { TeamCard, TeamMemberCard } from "@/lib/services/teams";
import {
  PixelAgent,
  PixelDesk,
  PixelTable,
  TEAM_PALETTES,
  type AgentState,
} from "./PixelAgent";
import { Cpu, FileText, Lock } from "lucide-react";
import type { AgentModel } from "@/lib/services/agent-models";
import type { ModelChoices } from "@/lib/agent-model-choices";
import { ModelPicker } from "./ModelPicker";

/**
 * One team's desk pod on the office floor.
 *
 * The pose is derived from the ledger, never chosen for looks - see
 * agentStateFor(). Every number that was on the old card is still here; the
 * office is a layer on top of the data, not a replacement for it.
 */

/** Each agent gets a name so they can refer to them. Cosmetic, deliberately.
 *  A team with 2+ manifest members is named per-member instead — the entry
 *  here is what the /teams mood line and the single-desk fallback show. */
export const AGENT_NAMES: Record<string, string> = {
  research: "the Research team",
  // The Admin room's ledger desk (named again 2026-09-22 when Cody joined the
  // room): the mood line says "Ada is waving", not "Admin is".
  admin: "Ada",
  security: "Sable",
  vault: "Vera",
  housekeeping: "Housekeeping",
  // The Quick Capture coding agent: not a manifest team, a desk in the Admin
  // room (coding-desk.ts).
  coding: "Cody",
};

export const AGENT_ROLES: Record<string, string> = {
  research: "Literature desk & the LabSerf bench",
  // A room card since 2026-09-22: Ada (the ledger team) + Cody.
  admin: "Inbox, calendar & G2 builds",
  security: "Audits, read-only",
  vault: "Filing & memory",
  // A room card (2026-09-22): vault + security share one.
  housekeeping: "Filing, memory & read-only audits",
  coding: "Builds and fixes G2 on request",
};

/** A desk's own role where its team id also names the room (Ada's desk in
 *  the Admin room); AGENT_ROLES holds the room's line. */
export const DESK_ROLES: Record<string, string> = {
  admin: "Inbox, commitments, calendar",
};

// Desk-scene geometry. Kept as numbers so the container is sized from the
// sprite rather than from a magic class, and so the arithmetic is checkable:
// the agent's top edge sits at SCENE_H - AGENT_BOTTOM - AGENT_SIZE = 6px.
const AGENT_SIZE = 72;
const AGENT_LEFT = 8;
const AGENT_BOTTOM = 26;
const SCENE_W = 120;
const SCENE_H = 104;

/** A desk's sprite colours: its own (team-member), else - for a room, whose
 *  desks are whole teams - that team's, else the team's. */
function paletteFor(teamId: string, memberId: string): string {
  if (`${teamId}-${memberId}` in TEAM_PALETTES) return `${teamId}-${memberId}`;
  if (memberId in TEAM_PALETTES) return memberId;
  return teamId;
}

const STATE_SEVERITY: Record<AgentState, number> = {
  idle: 0,
  ready: 1,
  working: 2,
  needs: 3,
  alert: 4,
};

export function agentStateFor(t: TeamCard): AgentState {
  // Order matters: the most urgent true thing wins. Failures outrank a full
  // review queue because a failed job produced nothing at all.
  let state: AgentState = "idle";
  // An overdue weekly run is an alert too: a run that never happened leaves no
  // failed job behind, so without this the pod looks healthy (team-cadence.ts).
  if (t.failed > 0 || t.cadenceStatus?.overdue) state = "alert";
  else if (t.needsReview > 0) state = "needs";
  else if (t.running > 0) state = "working";
  else if (t.queued > 0) state = "ready";
  // A member whose state is not ledger-derived (the LabSerf bench) can be
  // more urgent than the team tallies — a failed lab run must not hide
  // behind an empty queue.
  for (const member of t.memberCards) {
    const ms = memberStateFor(member);
    if (STATE_SEVERITY[ms] > STATE_SEVERITY[state]) state = ms;
  }
  return state;
}

export function memberStateFor(m: TeamMemberCard): AgentState {
  if (m.stateOverride) return m.stateOverride;
  if (m.failed > 0) return "alert";
  if (m.needsReview > 0) return "needs";
  if (m.running > 0) return "working";
  if (m.queued > 0) return "ready";
  return "idle";
}

export const STATE_COPY: Record<AgentState, { label: string; color: string }> = {
  alert: { label: "needs a hand", color: "var(--red)" },
  needs: { label: "waiting on you", color: "var(--amber)" },
  working: { label: "working", color: "var(--green)" },
  ready: { label: "queued up", color: "var(--cyan)" },
  idle: { label: "off the clock", color: "var(--ink-3)" },
};

function relative(iso: string | null): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "never";
  const mins = Math.floor((Date.now() - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function cadenceLabel(t: TeamCard): string {
  if (t.schedule_label) return t.schedule_label;
  const when = t.run_at ? ` ${t.run_at}` : "";
  if (t.cadence === "weekly") return `Mon${when}`;
  if (t.cadence === "weekdays") return `Weekdays${when}`;
  if (t.cadence === "daily") return `Daily${when}`;
  return "On demand";
}

/**
 * What this agent actually runs on.
 *
 * Read from the job modules at request time, not written down here — see
 * `agent-models.ts`. An agent whose kinds span runtimes gets one chip each,
 * most-used first, because "Vera is ollama" would be false for the half of their
 * work that goes to codex.
 */
export function ModelChips({ models }: { models: AgentModel[] }) {
  if (!models.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {models.map((m) => (
        <span
          key={`${m.runtime}:${m.model}`}
          title={`${m.kinds.length} job kind${m.kinds.length === 1 ? "" : "s"}: ${m.kinds.join(", ")}`}
          className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-1.5 py-px font-mono text-[10px] leading-4 text-[var(--ink-3)]"
        >
          <Cpu className="h-2.5 w-2.5" />
          <span className="text-[var(--ink-2)]">{m.runtime}</span>
          <span aria-hidden>·</span>
          <span className="text-[var(--ink)]">{m.model}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * The wall above a desk pod: name, role, when it runs, and what it is doing.
 * Shared by every pod on the floor.
 *
 * The cadence sits on its own line under the role, full width and allowed to
 * wrap. It used to be a `shrink-0` column on the right, and a manifest's
 * `schedule_label` is often a sentence ("Gmail + read-independent Slack DMs;
 * daily 05:00 + every 2h, 08:00-20:00"), which pushed the state label past the
 * card edge. It is not truncated either: they read this on a tablet, where a
 * `title` tooltip is unreachable.
 */
export function PodHeader({
  name,
  tag,
  icon,
  role,
  cadence,
  stateLabel,
  stateColor,
}: {
  name: string;
  tag: string;
  icon?: ReactNode;
  role: string;
  cadence: string;
  stateLabel: string;
  stateColor: string;
}) {
  return (
    <div className="office-wall flex items-start justify-between gap-2 border-b border-[var(--border)] px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ background: stateColor, boxShadow: `0 0 6px ${stateColor}` }}
          />
          <h3 className="truncate text-[13px] font-semibold text-[var(--ink)]">
            {name}
          </h3>
          <span className="truncate font-mono text-[10px] uppercase tracking-wide text-[var(--ink-3)]">
            {tag}
          </span>
          {icon}
        </div>
        <p className="mt-0.5 truncate text-[11px] text-[var(--ink-3)]">{role}</p>
        <p className="mt-0.5 break-words font-mono text-[10px] uppercase leading-snug tracking-wide text-[var(--ink-3)]">
          {cadence}
        </p>
      </div>
      <div
        className="shrink-0 whitespace-nowrap pt-px font-mono text-[10px] lowercase"
        style={{ color: stateColor }}
      >
        {stateLabel}
      </div>
    </div>
  );
}

export function Tally({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: string;
}) {
  const dim = value === 0;
  return (
    <div className="flex items-baseline justify-between gap-2 text-[11px]">
      <span className="font-mono uppercase tracking-wide text-[var(--ink-3)]">
        {label}
      </span>
      <span
        className="font-mono text-[13px] font-semibold tabular-nums"
        style={{ color: dim ? "var(--ink-3)" : (tone ?? "var(--ink)") }}
      >
        {value}
      </span>
    </div>
  );
}

function screenFor(state: AgentState): string {
  return state === "alert"
    ? "var(--red)"
    : state === "needs"
      ? "var(--amber)"
      : state === "working"
        ? "var(--green)"
        : "var(--accent)";
}

/**
 * A member room draws its desks at this scale. Two full-size scenes (2 x 120 +
 * gap) plus the 104px tally column need 364px of floor, and at lg:grid-cols-2
 * a card has 331 — so the desks overlapped each other and covered the tallies
 * ("UEUED"). At 0.8: 2 x 96 + 8 + 12 + 104 = 316. Both sprites are SVG with
 * crispEdges, so the smaller size stays sharp.
 */
const MEMBER_SCALE = 0.8;

/** One desk + one agent. The member room repeats this per member. */
export function DeskScene({
  paletteKey,
  state,
  title,
  scale = 1,
}: {
  paletteKey: string;
  state: AgentState;
  title: string;
  scale?: number;
}) {
  return (
    <div
      className="relative shrink-0"
      style={{ width: SCENE_W * scale, height: SCENE_H * scale }}
    >
      <div
        className="absolute"
        style={{ left: AGENT_LEFT * scale, bottom: AGENT_BOTTOM * scale }}
      >
        <PixelAgent
          team={paletteKey}
          state={state}
          size={AGENT_SIZE * scale}
          title={title}
        />
      </div>
      <div className="absolute" style={{ left: 0, bottom: 0 }}>
        <PixelDesk
          size={SCENE_W * scale}
          screen={screenFor(state)}
          lit={state !== "idle"}
        />
      </div>
    </div>
  );
}

type Side = "top" | "right" | "bottom" | "left";
const SIDES: Side[] = ["top", "right", "bottom", "left"];

// Table-room geometry (2026-09-21). Inline numbers for the same reason as the
// desk scene: Tailwind's JIT cannot drop an inline style. The room is sized to
// fit the 2-column /teams grid (a card body is ~307px wide at lg).
const ROOM_W = 300;
// Height leaves room for the bottom seat's plate at its tallest: name, a
// two-line role, and a two-line status (~66px below the seat at y=250).
const ROOM_H = 320;
const TABLE = 124;
const TABLE_X = (ROOM_W - TABLE) / 2;
const TABLE_Y = 92;
const SEAT_AGENT = 46; // sprite height; width is ~46 * 20/19
const SEAT_W = Math.round((SEAT_AGENT * 20) / 19);
// Side nameplates sit outside the table's edges, never over it.
const PLATE_W = Math.floor(TABLE_X - 6);

/** Seat i goes clockwise round the table: top, right, bottom, left, then doubles up. */
function seatFor(i: number, n: number): { side: Side; offset: number } {
  const side = SIDES[i % 4];
  const onSide = Math.floor((n - 1 - (i % 4)) / 4) + 1; // seats on this side
  const k = Math.floor(i / 4);
  return { side, offset: onSide === 1 ? 0.5 : k / (onSide - 1) };
}

/**
 * A team of three or more sits round one large square table (the owner,
 * 2026-09-21) instead of a row of desks, which stopped fitting past two.
 * Each seat is an agent with its nameplate; the laptop in front of them is lit
 * in their state colour. Poses are still derived, never chosen.
 */
function TableRoom({ team }: { team: TeamCard }) {
  const n = team.memberCards.length;
  return (
    <div className="relative mx-auto" style={{ width: ROOM_W, height: ROOM_H }}>
      {team.memberCards.map((m, i) => {
        const { side, offset } = seatFor(i, n);
        const ms = memberStateFor(m);
        const mCopy = STATE_COPY[ms];
        const paletteKey = paletteFor(team.id, m.id);
        // Position along the side, measured across the table's span.
        const spanX = TABLE_X + 18 + offset * (TABLE - 36);
        const spanY = TABLE_Y + 18 + offset * (TABLE - 36);
        const agent: React.CSSProperties = { position: "absolute", zIndex: side === "top" ? 0 : 2 };
        const plate: React.CSSProperties = { position: "absolute", width: PLATE_W };
        if (side === "top") {
          agent.left = spanX - SEAT_W / 2;
          agent.top = TABLE_Y + 12 - SEAT_AGENT;
          plate.left = spanX - PLATE_W / 2;
          plate.bottom = ROOM_H - (TABLE_Y + 12 - SEAT_AGENT) + 2;
        } else if (side === "bottom") {
          agent.left = spanX - SEAT_W / 2;
          agent.top = TABLE_Y + TABLE - 14;
          plate.left = spanX - PLATE_W / 2;
          plate.top = TABLE_Y + TABLE - 14 + SEAT_AGENT + 2;
        } else {
          const left = side === "left" ? TABLE_X - SEAT_W + 10 : TABLE_X + TABLE - 10;
          agent.left = left;
          agent.top = spanY - SEAT_AGENT / 2;
          plate.left = side === "left" ? TABLE_X - 4 - PLATE_W : TABLE_X + TABLE + 4;
          plate.top = spanY + SEAT_AGENT / 2 + 2;
        }
        return (
          <div key={m.id}>
            <div style={agent}>
              <PixelAgent
                team={paletteKey}
                state={ms}
                size={SEAT_AGENT}
                title={`${m.name} — ${mCopy.label}`}
              />
            </div>
            <div style={plate} className="text-center">
              <div className="flex items-center justify-center gap-1">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: mCopy.color }} />
                <span className="truncate text-[11px] font-semibold text-[var(--ink)]">{m.name}</span>
              </div>
              {/* Role wraps to two lines rather than truncating: an 82px side
                  plate cut "Experiment critique · negative results" mid-word,
                  and they read this on a tablet where a tooltip is unreachable. */}
              <p className="mt-px line-clamp-2 text-balance text-[9.5px] leading-[1.25] text-[var(--ink-3)]">
                {m.role}
              </p>
              <p
                className="mt-0.5 line-clamp-2 text-balance break-words font-mono text-[9.5px] lowercase leading-[1.25]"
                style={{ color: mCopy.color }}
              >
                {m.statusNote ?? mCopy.label}
              </p>
            </div>
          </div>
        );
      })}
      <div className="absolute" style={{ left: TABLE_X, top: TABLE_Y, zIndex: 1 }}>
        <PixelTable
          size={TABLE}
          seats={team.memberCards.map((m, i) => {
            const ms = memberStateFor(m);
            return { ...seatFor(i, n), screen: ms === "idle" ? null : screenFor(ms) };
          })}
        />
      </div>
    </div>
  );
}

export function TeamPod({
  team,
  modelDefaults = {},
  modelChoices,
}: {
  team: TeamCard;
  /** The runtime-wide defaults from the policy, for the picker's "inherit" label. */
  modelDefaults?: Partial<Record<string, string | null>>;
  /** Per-runtime choices resolved on the server; omitted = Claude aliases only. */
  modelChoices?: ModelChoices;
}) {
  const state = agentStateFor(team);
  const copy = STATE_COPY[state];
  // A team of one is its agent; a team of desks is named as a team and each
  // member gets a nameplate under their own desk.
  const multi = team.memberCards.length >= 2;
  const table = team.memberCards.length > 2;
  const name = multi ? team.name : (AGENT_NAMES[team.id] ?? team.name);
  // The "View N queued" link opens the ledger filtered to this team, where
  // Cody's queued runs do not appear; count only what the link will show.
  const ledgerQueued =
    team.queued -
    team.memberCards
      .filter((m) => m.desk === "coding")
      .reduce((n, m) => n + m.queued, 0);

  return (
    <div className="overflow-hidden rounded-[var(--radius-card)] border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-sm)] transition-colors hover:border-[var(--border-strong)]">
      {/* ---- Wall: nameplate ---- */}
      <PodHeader
        name={name}
        tag={team.id}
        icon={
          team.sensitivity_ceiling === "private" ? (
            <Lock
              className="h-3 w-3 shrink-0 text-[var(--ink-3)]"
              aria-label="Local models only"
            />
          ) : undefined
        }
        role={AGENT_ROLES[team.id] ?? team.summary}
        cadence={cadenceLabel(team)}
        stateLabel={copy.label}
        stateColor={copy.color}
      />

      {/* ---- Floor: the desk scene ----
          Dimensions are INLINE STYLES, not Tailwind arbitrary values. The first
          version used h-[92px]/w-[120px]/bottom-[26px], and Tailwind's JIT never
          generated them because this directory did not exist when the dev server
          started - so the container computed to 0x0, the sprites rendered
          outside the card, and `overflow-hidden` sliced them off. Inline styles
          cannot be dropped by a content scan. */}
      {table ? (
        <div className="office-floor relative px-3 pb-3 pt-3">
          <TableRoom team={team} />
          <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-0.5">
            <Tally label="needs you" value={team.needsReview} tone="var(--amber)" />
            <Tally label="running" value={team.running} tone="var(--green)" />
            <Tally label="queued" value={team.queued} tone="var(--cyan)" />
            <Tally label="failed" value={team.failed} tone="var(--red)" />
            <Tally label="done" value={team.completed} />
          </div>
        </div>
      ) : (
      <div className="office-floor relative flex items-end gap-3 px-3 pb-0 pt-3">
        {multi ? (
          /* The office room: one desk per member, each with its own nameplate.
             Member state is per-desk (Rho can be working while Argus waits on
             a lab run); the tallies to the right stay team-wide. */
          /* items-start, not items-end: nameplates wrap to different heights,
             and bottom-aligning the columns lifted one desk off the floor. */
          <div className="flex min-w-0 flex-1 items-start gap-2">
            {team.memberCards.map((m) => {
              const ms = memberStateFor(m);
              const mCopy = STATE_COPY[ms];
              const paletteKey =
                paletteFor(team.id, m.id);
              return (
                <div key={m.id} className="flex shrink-0 flex-col">
                  <DeskScene
                    paletteKey={paletteKey}
                    state={ms}
                    title={`${m.name} — ${mCopy.label}`}
                    scale={MEMBER_SCALE}
                  />
                  <div className="pb-3" style={{ width: SCENE_W * MEMBER_SCALE }}>
                    <div className="flex items-center gap-1.5">
                      <span
                        className="h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ background: mCopy.color }}
                      />
                      <span className="truncate text-[11px] font-semibold text-[var(--ink)]">
                        {m.name}
                      </span>
                    </div>
                    {/* Role and status wrap rather than truncate: at desk
                        width a one-line status cut "no trade last cycle" to
                        "no trade las…", and that line is the whole report. */}
                    <p className="line-clamp-2 text-[10px] leading-tight text-[var(--ink-3)]">
                      {m.role}
                    </p>
                    <p
                      className="mt-0.5 break-words font-mono text-[10px] lowercase leading-tight"
                      style={{ color: mCopy.color }}
                    >
                      {m.statusNote ?? mCopy.label}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <DeskScene
            paletteKey={team.id}
            state={state}
            title={`${name} — ${copy.label}`}
          />
        )}

        <div
          className={
            multi ? "w-[104px] shrink-0 space-y-0.5 pb-3" : "min-w-0 flex-1 space-y-0.5 pb-3"
          }
        >
          <Tally label="needs you" value={team.needsReview} tone="var(--amber)" />
          <Tally label="running" value={team.running} tone="var(--green)" />
          <Tally label="queued" value={team.queued} tone="var(--cyan)" />
          <Tally label="failed" value={team.failed} tone="var(--red)" />
          <Tally label="done" value={team.completed} />
        </div>
      </div>
      )}

      {/* ---- Model strip: per member when the team has separate desks.
             Claude rows are pickers. ---- */}
      <div className="border-t border-[var(--border)] px-3 py-2">
        {multi ? (
          <div className="space-y-1">
            {team.memberCards.map((m) => (
              <div key={m.id} className="flex items-center gap-1.5">
                <span
                  className="w-16 shrink-0 truncate font-mono text-[10px] uppercase tracking-wide text-[var(--ink-3)]"
                  title={m.name}
                >
                  {m.name}
                </span>
                {m.desk === "lab-advisor" || m.desk === "lab-figures" ? (
                  // Runs inside LabSerf's own sessions; G2 picks no model for it.
                  <span className="font-mono text-[10px] text-[var(--ink-3)]">runs in LabSerf</span>
                ) : (
                  <ModelPicker models={m.models} scope="desk" compact defaults={modelDefaults} choices={modelChoices} />
                )}
              </div>
            ))}
          </div>
        ) : (
          <ModelPicker models={team.models} scope="desk" compact defaults={modelDefaults} choices={modelChoices} />
        )}
      </div>

      {/* ---- Actions + output ---- */}
      <div className="border-t border-[var(--border)] px-3 py-2.5">
        {team.cadenceStatus?.overdue && (
          <p className="mb-2 text-[11px] font-medium text-[var(--red)]">
            Weekly run overdue · last successful job{" "}
            {relative(team.cadenceStatus.lastSuccessIso)}
          </p>
        )}
        {team.memberCards
          .filter((m) => m.desk === "coding" && m.failed > 0)
          .map((m) => (
            // Cody's runs are not ledger jobs, so a team-filtered /ops link
            // would not list them; his run monitor sits at the top of /ops.
            <Link
              key={m.id}
              href="/ops"
              className="mb-2 mr-2 inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--red)]/40 bg-[var(--red-soft)] px-2 py-1 text-[11px] font-medium text-[var(--red)] transition-colors hover:bg-[var(--red)]/20"
            >
              Review {m.name}&apos;s {m.failed} failed run{m.failed === 1 ? "" : "s"}
            </Link>
          ))}
        {ledgerQueued > 0 && (
          <Link
            href={`/ops?team=${team.id}`}
            className="mb-2 mr-2 inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2 py-1 text-[11px] font-medium text-[var(--cyan)] transition-colors hover:bg-[var(--surface-hover)]"
          >
            View {ledgerQueued} queued
          </Link>
        )}
        {team.needsReview > 0 && (
          <Link
            href={`/ops?team=${team.id}`}
            className="mb-2 inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--amber)]/40 bg-[var(--amber-soft)] px-2 py-1 text-[11px] font-medium text-[var(--amber)] transition-colors hover:bg-[var(--amber)]/20"
          >
            Review {team.needsReview} item{team.needsReview === 1 ? "" : "s"}
          </Link>
        )}

        {team.recentOutput.length > 0 ? (
          <ul className="space-y-1">
            {team.recentOutput.slice(0, 3).map((f) => (
              <li key={f.relPath} className="flex items-center gap-1.5 text-[11px]">
                <FileText className="h-3 w-3 shrink-0 text-[var(--ink-3)]" />
                <Link
                  href={`/vault/${f.relPath}`}
                  className="truncate text-[var(--ink-2)] hover:text-[var(--ink)] hover:underline"
                >
                  {f.name.replace(/\.md$/, "")}
                </Link>
                <span className="ml-auto shrink-0 font-mono text-[10px] text-[var(--ink-3)]">
                  {relative(f.mtimeIso)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[11px] text-[var(--ink-3)]">
            Nothing on the desk yet · last seen {relative(team.lastRunIso)}
          </p>
        )}
      </div>
    </div>
  );
}
