/**
 * Which model each agent actually runs on.
 *
 * The truth lives in Python: every job module in `.claude/scripts/jobs/`
 * declares `KIND`, `DEFAULT_RUNTIME`, and (optionally) `MODEL`, and each runtime
 * adapter declares a `DEFAULT_MODEL` for when a module leaves `MODEL = None`.
 * This module *reads* those declarations rather than restating them in a
 * manifest or a TypeScript table.
 *
 * That is deliberate. This repo's recurring failure mode is two copies of one
 * fact drifting apart — wiki_build's exclusions against memory_index's, the
 * drafting-tone spec across four files. A model name written down in a second
 * place would be wrong the first time a job is retuned, and wrong silently,
 * because nothing would fail. Parsing is fragile in a loud, obvious way
 * instead: a rename shows up as "unknown" on the card, not as a lie.
 *
 * Framework-free and read-only, like `teams.ts`: filesystem errors degrade to
 * an empty map so a missing scripts directory renders a card without model
 * chips rather than a 500.
 */

import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

const REPO = process.cwd();
const JOBS_DIR = path.join(REPO, ".claude", "scripts", "jobs");
const RUNTIMES_DIR = path.join(REPO, ".claude", "scripts", "runtimes");
const POLICY_FILE = path.join(REPO, ".claude", "data", "state", "model-policy.json");
const POLICY_SCRIPT = path.join(RUNTIMES_DIR, "model_policy.py");
const PYTHON =
  process.env.SECONDBRAIN_PYTHON ||
  "python";

export type AgentRuntime = "claude" | "codex" | "ollama";

/**
 * Where a kind's effective model came from, most specific first:
 * a per-kind pin from the /teams picker, the picker's runtime-wide default,
 * the module's own `MODEL`, or the runtime adapter's default.
 */
export type ModelSource = "policy-kind" | "policy-default" | "module" | "runtime";

export type KindRuntime = {
  kind: string;
  runtime: string;
  /** Null when nothing names a model and the runtime's own default applies. */
  model: string | null;
  source: ModelSource;
  /** What the module itself declares, for the picker's "as coded" label. */
  coded: string | null;
};

/** A runtime + model pairing, with the job kinds that use it. */
export type AgentModel = {
  runtime: string;
  model: string;
  kinds: string[];
  /** True when the /teams picker, not the code, chose this model. */
  pinned: boolean;
  /** The module default the picker would restore, for claude rows. */
  coded: string | null;
};

/**
 * The per-machine model policy the /teams picker writes
 * (`.claude/data/state/model-policy.json`, read by `runtimes/model_policy.py`
 * in the dispatcher). Same file, one writer: this module only reads it, and
 * every change goes through the Python CLI so validation lives in one place.
 */
export type ModelPolicy = {
  defaults: Record<string, string>;
  kinds: Record<string, Record<string, string>>;
  updated: string | null;
};

/** The picker's Claude choices live in `@/lib/agent-model-choices` (client-safe). */
export { CLAUDE_MODEL_CHOICES } from "@/lib/agent-model-choices";
import {
  CLAUDE_MODEL_CHOICES as CLAUDE_CHOICES,
  type ModelChoices,
} from "@/lib/agent-model-choices";
import os from "node:os";

/**
 * The model the Codex CLI would run with when no `-m` is passed: the
 * `model = "..."` line of `~/.codex/config.toml`. Read, not restated, so the
 * picker's "Codex CLI default" can say what that is today. Only that one line
 * is read; the file is otherwise theirs.
 */
export async function codexConfiguredModel(): Promise<string | null> {
  try {
    const text = await fs.readFile(path.join(os.homedir(), ".codex", "config.toml"), "utf8");
    const match = text.match(/^\s*model\s*=\s*"([^"]+)"/m);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

/** Model names Ollama has pulled on this machine, or [] when it is not up. */
export async function ollamaPulledModels(): Promise<string[] | null> {
  const base = process.env.OLLAMA_URL || "http://localhost:11434";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1500);
  try {
    const res = await fetch(`${base}/api/tags`, { signal: controller.signal, cache: "no-store" });
    if (!res.ok) return null;
    const body = (await res.json()) as { models?: Array<{ name?: string }> };
    return (body.models ?? [])
      .map((m) => (typeof m.name === "string" ? m.name : ""))
      .filter(Boolean)
      .sort();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * What the /teams picker may offer per runtime on this machine. Claude is the
 * CLI's fixed aliases; Codex is whatever `~/.codex/config.toml` names (any
 * other name is typed in - the CLI is the judge of whether it exists); Ollama
 * is the pulled list. Names already pinned in the policy are included so a
 * custom pick shows as selected after a reload. Reports rather than asserts:
 * an unreachable Ollama yields an empty list and a note saying so.
 */
export async function listModelChoices(): Promise<ModelChoices> {
  const [policy, codexDefault, pulled] = await Promise.all([
    readModelPolicy(), codexConfiguredModel(), ollamaPulledModels(),
  ]);
  const pinnedFor = (runtime: string): string[] => {
    const names = new Set<string>();
    if (policy.defaults[runtime]) names.add(policy.defaults[runtime]);
    for (const perKind of Object.values(policy.kinds)) {
      if (perKind[runtime]) names.add(perKind[runtime]);
    }
    return [...names];
  };
  const uniq = (list: string[]) => [...new Set(list.filter(Boolean))];
  return {
    runtimes: {
      claude: uniq([...CLAUDE_CHOICES, ...pinnedFor("claude")]),
      codex: uniq([...(codexDefault ? [codexDefault] : []), ...pinnedFor("codex")]),
      ollama: uniq([...(pulled ?? []), ...pinnedFor("ollama")]),
    },
    notes: {
      claude: "aliases the Claude CLI accepts; a spent window steps down on its own",
      codex: codexDefault
        ? `unpinned runs use ~/.codex/config.toml: ${codexDefault}`
        : "unpinned runs use ~/.codex/config.toml (no model line found here)",
      ollama: pulled === null
        ? "Ollama not reachable from this server; type a pulled model's name"
        : `${pulled.length} model${pulled.length === 1 ? "" : "s"} pulled on this machine`,
    },
  };
}

export async function readModelPolicy(): Promise<ModelPolicy> {
  try {
    const raw = JSON.parse(await fs.readFile(POLICY_FILE, "utf8")) as Record<string, unknown>;
    const defaults = raw.defaults && typeof raw.defaults === "object" ? raw.defaults as Record<string, string> : {};
    const kinds = raw.kinds && typeof raw.kinds === "object" ? raw.kinds as Record<string, Record<string, string>> : {};
    return {
      defaults: Object.fromEntries(Object.entries(defaults).filter(([, v]) => typeof v === "string" && v)),
      kinds: Object.fromEntries(
        Object.entries(kinds)
          .filter(([, v]) => v && typeof v === "object")
          .map(([k, v]) => [k, Object.fromEntries(Object.entries(v).filter(([, m]) => typeof m === "string" && m))]),
      ),
      updated: typeof raw.updated === "string" ? raw.updated : null,
    };
  } catch {
    return { defaults: {}, kinds: {}, updated: null };
  }
}

/**
 * Pin a model for some kinds (or, with `kinds: "*"`, set the runtime-wide
 * default). `model: null` clears the pin. Spawns the Python CLI so the name
 * validation and the file format have exactly one owner.
 */
export async function setAgentModel(input: {
  kinds: string[] | "*";
  runtime: AgentRuntime;
  model: string | null;
}): Promise<ModelPolicy> {
  const targets = input.kinds === "*" ? ["*"] : input.kinds;
  for (const kind of targets) {
    const args = input.model
      ? [POLICY_SCRIPT, "set", kind, input.runtime, input.model]
      : [POLICY_SCRIPT, "clear", kind, input.runtime];
    await new Promise<void>((resolve, reject) => {
      const child = spawn(PYTHON, args, {
        cwd: REPO, shell: false, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
        env: { ...process.env, CLAUDE_INVOKED_BY: "teams-model-picker" },
      });
      let out = "";
      let err = "";
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", (c: string) => { out += c; });
      child.stderr.on("data", (c: string) => { err += c; });
      const timer = setTimeout(() => { child.kill(); reject(new Error("Model policy update timed out.")); }, 20_000);
      child.on("error", (e) => { clearTimeout(timer); reject(e); });
      child.on("close", (code) => {
        clearTimeout(timer);
        let parsed: { error?: string } | null = null;
        try { parsed = JSON.parse(out.trim()); } catch { parsed = null; }
        if (code !== 0 || parsed?.error) {
          reject(new Error(parsed?.error || err.trim() || "Could not update the model policy."));
          return;
        }
        resolve();
      });
    });
  }
  return readModelPolicy();
}

/** Match a module-level `NAME = "value"` assignment, ignoring trailing comments. */
function assigned(source: string, name: string): string | null {
  const match = source.match(
    new RegExp(`^${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|(None))`, "m"),
  );
  if (!match) return null;
  if (match[3]) return null; // an explicit None means "use the runtime default"
  return match[1] ?? match[2] ?? null;
}

/**
 * Runtime fallbacks, read from each adapter's
 * `DEFAULT_MODEL = os.environ.get("VAR", "value")`.
 *
 * The env var is honoured here too, because the web app runs in the same shell
 * the dispatcher does — if they override `SECONDBRAIN_CLAUDE_MODEL`, the card
 * should say what will actually run, not what the source file suggests.
 */
async function runtimeDefaults(): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  let names: string[];
  try {
    names = await fs.readdir(RUNTIMES_DIR);
  } catch {
    return out;
  }
  for (const name of names) {
    if (!name.endsWith("_rt.py")) continue;
    try {
      const source = await fs.readFile(path.join(RUNTIMES_DIR, name), "utf8");
      const runtime = assigned(source, "RUNTIME");
      if (!runtime) continue;
      const decl = source.match(
        /^DEFAULT_MODEL\s*=\s*os\.environ\.get\(\s*"([^"]+)"\s*,\s*"([^"]*)"\s*\)/m,
      );
      if (!decl) continue;
      out[runtime] = process.env[decl[1]] || decl[2];
    } catch {
      continue;
    }
  }
  return out;
}

/** Every registered job kind with the runtime and model it will run on. */
export async function listKindRuntimes(): Promise<KindRuntime[]> {
  const [defaults, policy] = await Promise.all([runtimeDefaults(), readModelPolicy()]);
  let names: string[];
  try {
    names = await fs.readdir(JOBS_DIR);
  } catch {
    return [];
  }

  const out: KindRuntime[] = [];
  for (const name of names) {
    if (!name.endsWith(".py") || name.startsWith("_")) continue;
    try {
      const source = await fs.readFile(path.join(JOBS_DIR, name), "utf8");
      const kind = assigned(source, "KIND");
      const runtime = assigned(source, "DEFAULT_RUNTIME");
      if (!kind || !runtime) continue;
      const coded = assigned(source, "MODEL");
      const pinned = policy.kinds[kind]?.[runtime];
      const fallback = policy.defaults[runtime];
      const [model, modelSource]: [string | null, ModelSource] = pinned
        ? [pinned, "policy-kind"]
        : fallback
          ? [fallback, "policy-default"]
          : coded
            ? [coded, "module"]
            : [defaults[runtime] ?? null, "runtime"];
      out.push({ kind, runtime, model, source: modelSource, coded });
    } catch {
      continue;
    }
  }
  return out.sort((a, b) => a.kind.localeCompare(b.kind));
}

/**
 * Human label for a model slot. An empty Codex default is not missing data —
 * `codex_rt.DEFAULT_MODEL` is deliberately blank so their `~/.codex/config.toml`
 * stays the single place the coding model is set, and the card should say that
 * rather than imply nothing is configured.
 */
export function modelLabel(runtime: string, model: string | null): string {
  if (model) return model;
  if (runtime === "codex") return "Codex CLI default";
  return "runtime default";
}

/** Collapse a team's kinds into its distinct runtime + model pairings. */
export function foldModels(rows: KindRuntime[]): AgentModel[] {
  const byPair = new Map<string, AgentModel>();
  for (const row of rows) {
    const label = modelLabel(row.runtime, row.model);
    const key = `${row.runtime}:${label}`;
    const found = byPair.get(key);
    const pinned = row.source === "policy-kind" || row.source === "policy-default";
    if (found) {
      found.kinds.push(row.kind);
      found.pinned = found.pinned || pinned;
    } else {
      byPair.set(key, { runtime: row.runtime, model: label, kinds: [row.kind], pinned, coded: row.coded });
    }
  }
  // Most-used pairing first: it is the one that describes the agent.
  return [...byPair.values()].sort(
    (a, b) => b.kinds.length - a.kinds.length || a.runtime.localeCompare(b.runtime),
  );
}

/** The policy kind Cody's chip pins; mirrors `POLICY_KIND` in `g2_agent_run.py`. */
export const CODY_POLICY_KIND = "g2.build_fix";

/** The policy kinds the LabSerf desks' chips pin; mirrors `POLICY_KINDS` in `lab_run.py`. */
export const LAB_POLICY_KINDS = {
  "lab-analysis": "research.lab_analysis",
  "lab-cloning": "research.lab_cloning",
} as const;

/**
 * What a LabSerf desk runs on. `lab_run.py` asks the policy for its desk's
 * kind on the claude runtime only (the runner has no codex path), so the chip
 * is one Claude row: a pin wins, else the floor default, else the runtime
 * default - the same resolution Cody uses.
 */
export async function labDeskModels(desk: keyof typeof LAB_POLICY_KINDS): Promise<AgentModel[]> {
  const [defaults, policy] = await Promise.all([runtimeDefaults(), readModelPolicy()]);
  const kind = LAB_POLICY_KINDS[desk];
  const pinned = policy.kinds[kind]?.claude ?? policy.defaults.claude ?? null;
  return [{
    runtime: "claude",
    model: pinned ?? modelLabel("claude", defaults.claude || null),
    kinds: [kind],
    pinned: Boolean(pinned),
    coded: null,
  }];
}

/**
 * What the Quick Capture coding agent runs on. It calls the runtime adapters
 * with no explicit model, so its model *is* the runtime default — the same
 * value the team pods show for a `MODEL = None` job.
 */
export async function codingAgentModels(): Promise<AgentModel[]> {
  const [defaults, policy] = await Promise.all([runtimeDefaults(), readModelPolicy()]);
  return (["claude", "codex"] as const).map((runtime) => {
    // Cody is an ordinary desk: a pin on its chip wins, else the floor-wide
    // default for that runtime, else the runtime default it always used.
    const pinned = policy.kinds[CODY_POLICY_KIND]?.[runtime] ?? policy.defaults[runtime] ?? null;
    return {
      runtime,
      model: pinned ?? modelLabel(runtime, defaults[runtime] || null),
      kinds: [CODY_POLICY_KIND],
      pinned: Boolean(pinned),
      coded: null,
    };
  });
}
