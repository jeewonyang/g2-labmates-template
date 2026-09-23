/**
 * First-run setup status: what is connected on THIS machine, and what to do
 * about each thing that is not.
 *
 * The philosophy is manual-first. The PARA dashboard is fully usable with no
 * AI at all — capture, triage, tasks, notes, reviews are all hand-operated.
 * Linking an AI subscription (the Claude CLI, and/or ChatGPT's Codex CLI) is
 * what turns on agent automation, and a local Ollama adds private-content
 * triage. So "nothing linked" is a valid, quiet state — not an alarm. A row
 * only demands attention when something the user actually started is missing
 * a piece (a half-finished OAuth flow, a linked runtime with no Python to
 * spawn, a missing .env).
 *
 * Follows the `apps.ts` philosophy — verify, never assert. Everything here is
 * a local filesystem stat, a localhost probe, or a `--version` spawn; nothing
 * reads secret file contents (existence only) and nothing probes the network
 * beyond 127.0.0.1.
 */

import { access } from "node:fs/promises";
import { execFile } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { getLabEnvironment } from "@/lib/services/labNotebook";

const REPO = process.cwd();
const SECRETS = path.join(REPO, ".claude", "data", "secrets");
const PYTHON = process.env.SECONDBRAIN_PYTHON || "python";

/** Shipped placeholder values that must not count as "configured". */
const DEFAULT_CAPTURE_TOKENS = new Set([
  "dev-capture-token-change-me",
  "generate-a-long-random-token",
]);

export type SetupState = "ok" | "attention" | "off";
export type SetupGroup = "dashboard" | "agent" | "integrations";

export const GROUP_LABEL: Record<SetupGroup, { title: string; blurb: string }> = {
  dashboard: {
    title: "Dashboard",
    blurb: "Everything the manual PARA dashboard needs. No AI required.",
  },
  agent: {
    title: "AI agent layer",
    blurb:
      "Optional. Nothing here is required — without a linked subscription every workflow stays manual. Linking Claude and/or ChatGPT (Codex CLI) turns on agent automation; Ollama adds local-only triage of private content.",
  },
  integrations: {
    title: "Integrations",
    blurb:
      "Optional accounts the agent layer can read (and, for Gmail drafts and Calendar inserts, write after per-item approval).",
  },
};

export interface SetupItem {
  id: string;
  label: string;
  group: SetupGroup;
  state: SetupState;
  /** What was detected, including where the signal comes from. */
  detail: string;
  /**
   * The one action that sets this row up, written for someone with no coding
   * background. `run` is pasted into a terminal opened in this folder;
   * `ask` is pasted into a claude session (terminal -> type `claude`).
   */
  fix?: { kind: "run" | "ask"; text: string };
}

export interface SetupReport {
  items: SetupItem[];
  /** No row demands attention. Optional-and-absent is a quiet state, not an alarm. */
  ready: boolean;
  attention: number;
  /** At least one AI runtime is linked, so agent automation can run. */
  agentCapable: boolean;
}

async function exists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

function probeVersion(cmd: string, args: string[]): Promise<string | null> {
  return new Promise((resolve) => {
    try {
      const child = execFile(cmd, args, { timeout: 4000, windowsHide: true },
        (error, stdout, stderr) => {
          if (error) return resolve(null);
          resolve((stdout || stderr).trim().split(/\r?\n/)[0] || "found");
        });
      child.on("error", () => resolve(null));
    } catch {
      resolve(null);
    }
  });
}

async function probeOllama(): Promise<string | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 900);
  try {
    const response = await fetch("http://127.0.0.1:11434/api/version", {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { version?: string };
    return body.version ?? "running";
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function getSetupReport(): Promise<SetupReport> {
  const home = os.homedir();

  const [
    bootstrapPresent,
    userProfile,
    vaultReady,
    envPresent,
    claudeCreds,
    codexCreds,
    googleToken,
    googleClient,
    slackEnv,
    githubEnv,
    ollama,
    python,
  ] = await Promise.all([
    exists(path.join(REPO, "VAULT", "Memory", "BOOTSTRAP.md")),
    exists(path.join(REPO, "VAULT", "Memory", "USER.md")),
    exists(path.join(REPO, "VAULT", "G2OS-Staging")),
    exists(path.join(REPO, ".env")),
    exists(path.join(home, ".claude", ".credentials.json")),
    exists(path.join(home, ".codex", "auth.json")),
    exists(path.join(SECRETS, "google_token.json")),
    exists(path.join(SECRETS, "credentials.json")),
    exists(path.join(SECRETS, "slack.env")),
    exists(path.join(SECRETS, "github.env")),
    probeOllama(),
    probeVersion(PYTHON, ["--version"]),
  ]);

  const captureToken = (process.env.CAPTURE_API_TOKEN ?? "").trim();
  const lab = getLabEnvironment();
  // Any linked runtime means the user has opted into the agent layer, so its
  // supporting pieces (Python, vault tree, onboarding) become worth flagging.
  const agentCapable = claudeCreds || codexCreds || Boolean(ollama);
  const onboarded = userProfile && !bootstrapPresent;

  const items: SetupItem[] = [
    {
      id: "env",
      label: "Environment file",
      group: "dashboard",
      state: !envPresent || DEFAULT_CAPTURE_TOKENS.has(captureToken) ? "attention" : "ok",
      detail: !envPresent
        ? ".env does not exist yet."
        : DEFAULT_CAPTURE_TOKENS.has(captureToken)
          ? ".env exists, but CAPTURE_API_TOKEN is still the shipped placeholder — rotate it before exposing this server beyond localhost."
          : ".env present with a non-default capture token.",
      fix: !envPresent
        ? { kind: "run", text: "cp .env.example .env" }
        : DEFAULT_CAPTURE_TOKENS.has(captureToken)
          ? {
              kind: "ask",
              text: "Replace the placeholder tokens in my .env with fresh random values.",
            }
          : undefined,
    },
    {
      id: "claude",
      label: "Claude subscription (CLI)",
      group: "agent",
      state: claudeCreds ? "ok" : "off",
      detail: claudeCreds
        ? "CLI login detected at ~/.claude — a machine-wide login shared by every repo on this machine, not something this repo stores. Agent automation is available."
        : "Not linked. The dashboard stays fully manual — link this (or Codex) whenever you want agent automation. Claude is the recommended runtime: it powers the research, admin, and vault teams plus the interactive skills.",
      fix: claudeCreds ? undefined : { kind: "run", text: "claude" },
    },
    {
      id: "codex",
      label: "ChatGPT subscription (Codex CLI)",
      group: "agent",
      state: codexCreds ? "ok" : "off",
      detail: codexCreds
        ? "CLI login detected at ~/.codex (machine-wide). The security team can run."
        : "Not linked. Optional second runtime billed to a ChatGPT subscription; without it the codex-routed security team stays idle.",
      fix: codexCreds ? undefined : { kind: "run", text: "codex login" },
    },
    {
      id: "ollama",
      label: "Ollama (local models)",
      group: "agent",
      state: ollama ? "ok" : "off",
      detail: ollama
        ? `Answering on 127.0.0.1:11434 (v${ollama}). Private-content triage and bge-m3 embeddings are available.`
        : "Not running on 127.0.0.1:11434. Optional and free — it triages private vault content locally (that content never goes to cloud models, so without Ollama it simply is not auto-triaged) and provides multilingual embeddings.",
      fix: ollama ? undefined : { kind: "run", text: "ollama pull bge-m3" },
    },
    {
      id: "python",
      label: "Python runtime",
      group: "agent",
      // Python only matters once some runtime is linked; before that its
      // absence is part of the same quiet "no agent layer yet" state.
      state: python ? "ok" : agentCapable ? "attention" : "off",
      detail: python
        ? `${python} — resolved from ${process.env.SECONDBRAIN_PYTHON ? "SECONDBRAIN_PYTHON" : "PATH"}. Agent scripts, capture triage, and memory search spawn this interpreter.`
        : agentCapable
          ? `An AI runtime is linked but "${PYTHON} --version" failed — the agent scripts cannot run without it.`
          : `Not found ("${PYTHON} --version" failed). Needed only when you adopt the agent layer.`,
      fix: python
        ? undefined
        : {
            kind: "ask",
            text: "Install Python for my Second Brain agent scripts and point SECONDBRAIN_PYTHON in .env at it.",
          },
    },
    {
      id: "vault",
      label: "Vault folder tree",
      group: "agent",
      state: vaultReady ? "ok" : agentCapable ? "attention" : "off",
      detail: vaultReady
        ? "All four sensitivity-tiered vaults exist on disk."
        : "Your vault does not exist yet. It is created on this machine and never committed; the agent layer files captures, papers and notebook entries into it.",
      fix: vaultReady ? undefined : { kind: "run", text: "python .claude/scripts/init_vault.py" },
    },
    {
      id: "onboarding",
      label: "Onboarding interview",
      group: "agent",
      state: onboarded ? "ok" : claudeCreds ? "attention" : "off",
      detail: onboarded
        ? "Completed - VAULT/Memory/USER.md exists and BOOTSTRAP.md has been retired."
        : claudeCreds
          ? "The agent has not met you yet: the first claude session in this folder runs the interview (it creates your vault, fills USER.md, and maps your folders)."
          : "Waits for a linked Claude CLI: the first claude session in this repo runs the interview that personalizes the agent.",
      fix: !onboarded && claudeCreds
        ? { kind: "ask", text: "Run the onboarding in vault-template/Memory/BOOTSTRAP.md" }
        : undefined,
    },
    {
      id: "labserf",
      label: "LabSerf bench (lab notebook)",
      group: "agent",
      state: lab.labserf && lab.python ? "ok" : "off",
      detail: lab.labserf && lab.python
        ? `Agents and skills found; analyses run with ${lab.pythonPath}. Research -> Lab notebook -> Launch.`
        : `Optional. ${lab.problems.join(" ")} Flow cytometry, ultrasound and primer-design runs need the packages in labserf/requirements.txt.`,
      fix: lab.labserf && lab.python
        ? undefined
        : { kind: "run", text: "pip install -r labserf/requirements.txt" },
    },
    {
      id: "google",
      label: "Google (Gmail drafts · Calendar · Drive)",
      group: "integrations",
      state: googleToken ? "ok" : googleClient ? "attention" : "off",
      detail: googleToken
        ? "OAuth token stored in .claude/data/secrets/ — reads plus the two approved writes (draft create, event insert)."
        : googleClient
          ? "OAuth client found but no token yet — finish the consent flow."
          : "Not configured; email drafting and calendar proposals stay off.",
      fix: googleToken
        ? undefined
        : {
            kind: "ask",
            text: "Walk me through connecting my Google account step by step, using docs/INTEGRATIONS_SETUP.md. I have no coding experience.",
          },
    },
    {
      id: "slack",
      label: "Slack (read-only)",
      group: "integrations",
      state: slackEnv ? "ok" : "off",
      detail: slackEnv
        ? "Token file present. Reads and drafts only — nothing is ever posted."
        : "No token file; Slack catch-up and DM drafting stay off.",
      fix: slackEnv
        ? undefined
        : {
            kind: "ask",
            text: "Walk me through connecting Slack (read-only) step by step, using docs/INTEGRATIONS_SETUP.md. I have no coding experience.",
          },
    },
    {
      id: "github",
      label: "GitHub notifications",
      group: "integrations",
      state: githubEnv ? "ok" : "off",
      detail: githubEnv ? "Token file present." : "No token file; the GitHub queries stay off.",
      fix: githubEnv
        ? undefined
        : {
            kind: "ask",
            text: "Walk me through connecting GitHub notifications step by step, using docs/INTEGRATIONS_SETUP.md.",
          },
    },
  ];

  const attention = items.filter((i) => i.state === "attention").length;
  return { items, ready: attention === 0, attention, agentCapable };
}
