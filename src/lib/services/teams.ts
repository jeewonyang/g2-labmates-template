/**
 * Team service: groups ledger jobs by the team that owns their kind.
 *
 * Reads the SAME manifests `.claude/scripts/teams.py` reads
 * (`.claude/agents/teams/*.json`) rather than duplicating the mapping in
 * TypeScript. That is why the manifests are JSON and not YAML: package.json has
 * no yaml parser, and a second copy of "which kinds belong to which team" would
 * drift the moment a kind moved.
 *
 * Framework-free and read-only, following the `secondbrain.ts` / `ledger.ts`
 * pattern: no Prisma, no Next imports, and filesystem errors return empty
 * rather than throwing, so a missing manifest directory renders an empty state
 * instead of a 500.
 */

import fs from "node:fs/promises";
import path from "node:path";
import { listJobs, type Job, type JobStatus } from "./ledger";
import { cadenceStatus, type CadenceStatus } from "./team-cadence";
import {
  foldModels,
  labDeskModels,
  listKindRuntimes,
  type AgentModel,
} from "./agent-models";
import { LABSERF_ROOT, listLabRuns, type LabRun } from "./labNotebook";

const REPO = process.cwd();
const TEAMS_DIR = path.join(REPO, ".claude", "agents", "teams");
const MEMORY = path.join(REPO, "VAULT", "Memory");
const NEGATIVE_LEDGER = path.join(LABSERF_ROOT, "LabMemory", "negative_results.jsonl");

/**
 * A named agent inside a team. Most teams are one agent and declare no
 * members; a manifest lists members only when the team genuinely has separate
 * desks - Research has Rho (the ledger kinds) and Argus (the LabSerf bench,
 * which has no ledger kinds because lab runs are launched from the notebook,
 * not the dispatcher).
 */
export interface TeamMemberManifest {
  id: string;
  name: string;
  role: string;
  kinds: string[];
  /** "lab-bench" marks the desk whose status comes from the lab runner's run files. */
  desk?: string;
  /** Set on a room card's member desk: the team this desk stands for. */
  teamId?: string;
}

export type MemberState = "idle" | "ready" | "working" | "needs" | "alert";

export interface TeamMemberCard extends TeamMemberManifest {
  queued: number;
  running: number;
  needsReview: number;
  failed: number;
  models: AgentModel[];
  /** Set for desks whose state is not derivable from ledger tallies. */
  stateOverride: MemberState | null;
  statusNote: string | null;
}

export interface TeamManifest {
  id: string;
  name: string;
  summary: string;
  order: number;
  enabled: boolean;
  cadence: "daily" | "weekdays" | "weekly" | "manual";
  run_at: string | null;
  schedule_label?: string;
  producer: string | null;
  sensitivity_ceiling: "private" | "internal";
  kinds: string[];
  members?: TeamMemberManifest[];
  notes?: string[];
  /**
   * Two teams that share one room on /teams (2026-09-22: vault + security =
   * Housekeeping). Presentation only - each keeps its manifest, producer,
   * cadence and review rules.
   */
  room?: { id: string; name: string };
}

export interface TeamCard extends TeamManifest {
  queued: number;
  running: number;
  needsReview: number;
  failed: number;
  completed: number;
  lastRunIso: string | null;
  /** Weekly teams only: when work last succeeded, and whether a run is overdue. */
  cadenceStatus: CadenceStatus | null;
  recentOutput: OutputFile[];
  /** Runtime + model pairings this team's kinds actually run on. */
  models: AgentModel[];
  /** Per-member cards when the manifest declares 2+ members; else empty. */
  memberCards: TeamMemberCard[];
}

export interface OutputFile {
  name: string;
  relPath: string;
  mtimeIso: string;
}

/** Where each team's visible output lands, for the "recent output" strip. */
const OUTPUT_DIRS: Record<string, string[]> = {
  research: ["research/digests", "projects", "meetings/actions"],
  admin: ["drafts/active", "admin/commitments", "admin"],
  security: ["security"],
  vault: ["wiki", "daily"],
  hr: ["hr/packets", "design/reviews"],
};

export async function listManifests(): Promise<TeamManifest[]> {
  let names: string[];
  try {
    names = await fs.readdir(TEAMS_DIR);
  } catch {
    return [];
  }

  const out: TeamManifest[] = [];
  for (const n of names) {
    if (!n.endsWith(".json")) continue;
    try {
      const raw = await fs.readFile(path.join(TEAMS_DIR, n), "utf8");
      const m = JSON.parse(raw) as Partial<TeamManifest>;
      if (!m.id || !Array.isArray(m.kinds)) continue;
      out.push({
        id: m.id,
        name: m.name ?? m.id,
        summary: m.summary ?? "",
        order: typeof m.order === "number" ? m.order : 50,
        enabled: m.enabled !== false,
        cadence: (m.cadence ?? "manual") as TeamManifest["cadence"],
        run_at: m.run_at ?? null,
        schedule_label:
          typeof m.schedule_label === "string" ? m.schedule_label : undefined,
        producer: m.producer ?? null,
        // Fail closed, matching teams.py: an absent or unknown ceiling is
        // private, so a malformed manifest cannot widen its own routing.
        sensitivity_ceiling:
          m.sensitivity_ceiling === "internal" ? "internal" : "private",
        kinds: m.kinds as string[],
        members: Array.isArray(m.members)
          ? (m.members as Partial<TeamMemberManifest>[]).flatMap((member) =>
              member && typeof member.id === "string" && typeof member.name === "string"
                ? [{
                    id: member.id,
                    name: member.name,
                    role: typeof member.role === "string" ? member.role : "",
                    kinds: Array.isArray(member.kinds) ? (member.kinds as string[]) : [],
                    ...(typeof member.desk === "string" ? { desk: member.desk } : {}),
                  }]
                : [],
            )
          : undefined,
        notes: Array.isArray(m.notes) ? (m.notes as string[]) : [],
        ...(m.room && typeof m.room.id === "string" && typeof m.room.name === "string"
          ? { room: { id: m.room.id, name: m.room.name } }
          : {}),
      });
    } catch {
      continue; // one bad manifest must not blank the whole page
    }
  }
  return out.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
}

/**
 * Files that live in an output directory but are INPUT they maintain by hand.
 * Listing the markets watchlist as "recent output" implies the agent wrote it,
 * which is exactly backwards and would make them doubt what else it touched.
 */
const NOT_OUTPUT = new Set(["watchlist.md", "index.md", "README.md", "notes.md"]);

async function recentOutput(teamId: string, limit = 4): Promise<OutputFile[]> {
  const dirs = OUTPUT_DIRS[teamId] ?? [];
  const files: OutputFile[] = [];

  for (const rel of dirs) {
    const abs = path.join(MEMORY, rel);
    let names: string[];
    try {
      names = await fs.readdir(abs);
    } catch {
      continue;
    }
    for (const n of names) {
      if (n.startsWith(".")) continue;
      try {
        const st = await fs.stat(path.join(abs, n));
        if (st.isDirectory()) {
          // One level down: the lab-search team writes one folder per lab
          // (hr/packets/<lab>/final.md). history/ is kept out - every earlier
          // round is preserved there, but it is not "recent output".
          if (n === "history") continue;
          let inner: string[];
          try {
            inner = await fs.readdir(path.join(abs, n));
          } catch {
            continue;
          }
          for (const m of inner) {
            if (!m.endsWith(".md") || NOT_OUTPUT.has(m) || m.startsWith(".")) continue;
            try {
              const ist = await fs.stat(path.join(abs, n, m));
              if (!ist.isFile()) continue;
              files.push({
                name: `${n}/${m}`,
                relPath: `${rel}/${n}/${m}`,
                mtimeIso: ist.mtime.toISOString(),
              });
            } catch {
              continue;
            }
          }
          continue;
        }
        if (!st.isFile() || !n.endsWith(".md") || NOT_OUTPUT.has(n)) continue;
        files.push({
          name: n,
          relPath: `${rel}/${n}`,
          mtimeIso: st.mtime.toISOString(),
        });
      } catch {
        continue;
      }
    }
  }

  // Output dirs can nest (admin lists both "admin/commitments" and "admin",
  // whose one-level-down scan finds commitments/ again), so one file could be
  // listed twice - a duplicate React key and a doubled row on the admin pod.
  const seen = new Set<string>();
  return files
    .filter((f) => !seen.has(f.relPath) && Boolean(seen.add(f.relPath)))
    .sort((a, b) => b.mtimeIso.localeCompare(a.mtimeIso))
    .slice(0, limit);
}

/** Which lab runs each LabSerf desk owns. Argus's bench (2026-09-22) is
 *  every assay at once; the split desks are kept for a manifest that still
 *  names them. */
const LAB_DESK_ASSAYS: Record<string, string[]> = {
  "lab-analysis": ["flow", "ultrasound"],
  "lab-cloning": ["primer-design"],
  "lab-bench": ["flow", "ultrasound", "primer-design"],
};

/**
 * A LabSerf desk's status, read from the lab runner's own run files - the
 * same files /research/notebook shows. Reported, never asserted: a failed run
 * they have not cleared is an alert, a live run is working, and everything else
 * is at rest with the last outcome as its note.
 */
function labRunDesk(desk: string, runs: LabRun[]): {
  stateOverride: MemberState;
  statusNote: string;
  queued: number;
  running: number;
  failed: number;
} {
  const assays = LAB_DESK_ASSAYS[desk] ?? [];
  const mine = runs.filter((r) => assays.includes(r.assay));
  const queued = mine.filter((r) => r.status === "queued").length;
  const running = mine.filter((r) => r.status === "running" || r.status === "cancel_requested").length;
  const failed = mine.filter((r) => r.status === "failed" && !r.dismissedAt).length;
  const tally = { queued, running, failed };
  if (running) return { ...tally, stateOverride: "working", statusNote: "analysis running" };
  if (failed) return { ...tally, stateOverride: "alert", statusNote: "last run failed" };
  if (queued) return { ...tally, stateOverride: "ready", statusNote: `${queued} run${queued === 1 ? "" : "s"} waiting` };
  const last = mine[0];
  if (!last) return { ...tally, stateOverride: "idle", statusNote: "no runs yet" };
  return {
    ...tally,
    stateOverride: "idle",
    statusNote: last.notebookTitle ? `last: ${last.notebookTitle}` : `last run ${last.status}`,
  };
}

/** The Advisor's desk: the negative-result ledger it keeps, read as recorded. */
async function advisorDeskStatus(): Promise<{ stateOverride: MemberState; statusNote: string }> {
  try {
    const rows = (await fs.readFile(NEGATIVE_LEDGER, "utf8"))
      .split(/\r?\n/)
      .filter((line) => line.trim() && !line.startsWith("#"));
    let open = 0;
    for (const line of rows) {
      try {
        if (!(JSON.parse(line) as { resolved?: unknown }).resolved) open += 1;
      } catch {
        // a hand-edited bad line is not a result
      }
    }
    return {
      stateOverride: "idle",
      statusNote: rows.length
        ? `${rows.length} negative result${rows.length === 1 ? "" : "s"} · ${open} open`
        : "ledger empty",
    };
  } catch {
    return { stateOverride: "idle", statusNote: "LabSerf not on this machine" };
  }
}

export async function listTeamCards(): Promise<TeamCard[]> {
  const manifests = await listManifests();
  if (manifests.length === 0) return [];

  const jobs = await listJobs({});
  const kindRuntimes = await listKindRuntimes();
  const runtimeByKind = new Map(kindRuntimes.map((row) => [row.kind, row]));
  const byKind = new Map<string, Job[]>();
  for (const j of jobs) {
    if (!j.kind) continue;
    const arr = byKind.get(j.kind);
    if (arr) arr.push(j);
    else byKind.set(j.kind, [j]);
  }

  const count = (js: Job[], s: JobStatus) =>
    js.filter((j) => j.status === s).length;

  const cards: TeamCard[] = [];
  let labRuns: LabRun[] | undefined;
  for (const m of manifests) {
    // A retired team (disabled, owns no kinds) has no desk on the floor.
    if (!m.enabled && m.kinds.length === 0) continue;
    const mine = m.kinds.flatMap((k) => byKind.get(k) ?? []);
    const stamps = mine
      .map((j) => j.updated_ts ?? j.created_ts)
      .filter((t): t is string => Boolean(t))
      .sort();

    const memberCards: TeamMemberCard[] = [];
    if ((m.members?.length ?? 0) >= 2) {
      for (const member of m.members ?? []) {
        const theirs = member.kinds.flatMap((k) => byKind.get(k) ?? []);
        const base = {
          ...member,
          queued: count(theirs, "created"),
          running: count(theirs, "claimed"),
          needsReview: count(theirs, "needs_review"),
          failed: count(theirs, "failed"),
          models: foldModels(
            member.kinds
              .map((k) => runtimeByKind.get(k))
              .filter((row): row is NonNullable<typeof row> => Boolean(row)),
          ),
          stateOverride: null as MemberState | null,
          statusNote: null as string | null,
        };
        if (member.desk === "lab-analysis" || member.desk === "lab-cloning") {
          labRuns ??= await listLabRuns(50, { includeDismissed: true });
          Object.assign(base, labRunDesk(member.desk, labRuns));
          base.models = await labDeskModels(member.desk);
        } else if (member.desk === "lab-bench") {
          // Argus: the LabSerf agents as one desk. Run files decide the pose;
          // at rest with no runs, the negative-result ledger is the note.
          labRuns ??= await listLabRuns(50, { includeDismissed: true });
          Object.assign(base, labRunDesk(member.desk, labRuns));
          if (base.statusNote === "no runs yet") {
            base.statusNote = (await advisorDeskStatus()).statusNote;
          }
          // One chip per distinct runtime+model: analysis and cloning usually
          // resolve to the same one, and a picker row per kind would repeat it.
          const benchModels: AgentModel[] = [];
          for (const bm of [
            ...(await labDeskModels("lab-analysis")),
            ...(await labDeskModels("lab-cloning")),
          ]) {
            const same = benchModels.find(
              (x) => x.runtime === bm.runtime && x.model === bm.model,
            );
            if (same) {
              same.kinds = [...same.kinds, ...bm.kinds];
              same.pinned = same.pinned || bm.pinned;
            }
            else benchModels.push({ ...bm, kinds: [...bm.kinds] });
          }
          base.models = benchModels;
        } else if (member.desk === "lab-advisor") {
          Object.assign(base, await advisorDeskStatus());
        } else if (member.desk === "lab-figures") {
          // LabSerf's figure-designer is a subagent of its analysis agent and
          // runs inside LabSerf's own Claude Code sessions; G2's runner does
          // not spawn it, and saying otherwise would be an assertion.
          base.stateOverride = "idle";
          base.statusNote = "reviews figures inside LabSerf";
        }
        memberCards.push(base);
      }
    }

    cards.push({
      ...m,
      queued: count(mine, "created"),
      running: count(mine, "claimed"),
      needsReview: count(mine, "needs_review"),
      failed: count(mine, "failed"),
      completed: count(mine, "completed"),
      lastRunIso: stamps.length ? stamps[stamps.length - 1] : null,
      cadenceStatus: m.enabled ? cadenceStatus(m.cadence, mine, new Date()) : null,
      recentOutput: await recentOutput(m.id),
      models: foldModels(
        m.kinds
          .map((k) => runtimeByKind.get(k))
          .filter((row): row is NonNullable<typeof row> => Boolean(row)),
      ),
      memberCards,
    });
  }
  return cards;
}

/**
 * Fold teams that share a `room` into one card whose desks are the teams.
 * `personaFor` names each desk (the persona map lives with the pod component).
 * The room sits where its first team sat in manifest order.
 */
export function groupRooms(
  cards: TeamCard[],
  personaFor: (teamId: string) => { name: string; role: string },
): TeamCard[] {
  const out: TeamCard[] = [];
  const placed = new Set<string>();
  for (const c of cards) {
    if (!c.room) {
      out.push(c);
      continue;
    }
    if (placed.has(c.room.id)) continue;
    placed.add(c.room.id);
    const group = cards.filter((x) => x.room?.id === c.room?.id);
    if (group.length < 2) {
      out.push(c);
      continue;
    }
    const sum = (k: "queued" | "running" | "needsReview" | "failed" | "completed") =>
      group.reduce((n, t) => n + t[k], 0);
    const stamps = group.map((t) => t.lastRunIso).filter((t): t is string => Boolean(t)).sort();
    const overdue = group.find((t) => t.cadenceStatus?.overdue)?.cadenceStatus ?? null;
    out.push({
      ...c,
      id: c.room.id,
      name: c.room.name,
      summary: group.map((t) => t.summary).join(" "),
      cadence: c.cadence,
      schedule_label: group
        .map((t) => `${personaFor(t.id).name}: ${t.schedule_label ?? t.cadence}`)
        .join(" · "),
      // The lock means "local models only"; a room shows it only when every
      // team in it is private.
      sensitivity_ceiling: group.every((t) => t.sensitivity_ceiling === "private")
        ? "private"
        : "internal",
      kinds: group.flatMap((t) => t.kinds),
      members: undefined,
      notes: group.flatMap((t) => t.notes ?? []),
      queued: sum("queued"),
      running: sum("running"),
      needsReview: sum("needsReview"),
      failed: sum("failed"),
      completed: sum("completed"),
      lastRunIso: stamps.length ? stamps[stamps.length - 1] : null,
      cadenceStatus: overdue ?? c.cadenceStatus,
      recentOutput: group
        .flatMap((t) => t.recentOutput)
        .sort((a, b) => b.mtimeIso.localeCompare(a.mtimeIso))
        .slice(0, 4),
      models: group.flatMap((t) => t.models),
      memberCards: group.map((t) => ({
        id: t.id,
        teamId: t.id,
        name: personaFor(t.id).name,
        role: personaFor(t.id).role,
        kinds: t.kinds,
        queued: t.queued,
        running: t.running,
        needsReview: t.needsReview,
        failed: t.failed,
        models: t.models,
        // An overdue weekly run leaves no failed job behind (team-cadence.ts),
        // so the desk says so itself rather than looking asleep.
        stateOverride: t.cadenceStatus?.overdue ? "alert" : null,
        statusNote: t.cadenceStatus?.overdue ? "weekly run overdue" : null,
      })),
    });
  }
  return out;
}

/** Team ids a /ops `team=` filter selects: the team itself, or every team in a room. */
export async function teamsForFilter(filter: string): Promise<Set<string>> {
  const ids = new Set<string>();
  for (const m of await listManifests()) {
    if (m.id === filter || m.room?.id === filter) ids.add(m.id);
  }
  return ids;
}

/** kind -> team id, for the team filter on /ops. */
export async function kindToTeam(): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  for (const m of await listManifests()) {
    for (const k of m.kinds) out[k] = m.id;
  }
  return out;
}
