/**
 * What the /teams model picker offers per runtime, and the labels it shows.
 *
 * Kept apart from `services/agent-models.ts` on purpose: that module spawns
 * Python (`node:child_process`) to write the policy, and a client component
 * that imported even one constant from it would drag the server-only import
 * into the browser bundle.
 *
 * Only Claude has a fixed list here: its aliases are the CLI's own and
 * `failover.MODEL_BACKUP` knows how to step down from them. Codex and Ollama
 * choices are discovered on the server at render time (`listModelChoices`):
 * the Codex CLI's configured model from `~/.codex/config.toml`, and whatever
 * Ollama has actually pulled. Every runtime also takes a typed name - the
 * policy validates it, the runtime CLI is the judge of whether it exists.
 */
export type ModelRuntime = "claude" | "codex" | "ollama";

export const CLAUDE_MODEL_CHOICES = ["fable", "opus", "sonnet", "haiku"] as const;

export const MODEL_LABELS: Record<string, string> = {
  fable: "Fable 5.1",
  opus: "Opus",
  sonnet: "Sonnet",
  haiku: "Haiku",
};

/** Kept for existing imports; same table. */
export const CLAUDE_MODEL_LABELS = MODEL_LABELS;

/** Per-runtime choices as the server resolved them for this machine. */
export type ModelChoices = {
  runtimes: Record<ModelRuntime, string[]>;
  /** One line per runtime saying where its unpinned default comes from. */
  notes: Partial<Record<ModelRuntime, string>>;
};

export const EMPTY_CHOICES: ModelChoices = {
  runtimes: { claude: [...CLAUDE_MODEL_CHOICES], codex: [], ollama: [] },
  notes: {},
};

export function isModelRuntime(value: string): value is ModelRuntime {
  return value === "claude" || value === "codex" || value === "ollama";
}
