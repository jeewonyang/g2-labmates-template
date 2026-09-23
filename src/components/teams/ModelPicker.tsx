"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Cpu, Pin } from "lucide-react";
import { setAgentModelAction } from "@/lib/actions";
import {
  EMPTY_CHOICES,
  MODEL_LABELS,
  isModelRuntime,
  type ModelChoices,
} from "@/lib/agent-model-choices";
import type { AgentModel } from "@/lib/services/agent-models";

const CUSTOM = "__custom__";

/**
 * What an agent runs on, editable on every desk (the owner, 2026-09-18: first
 * Claude rows only, then "all agents, and codex too").
 *
 * Each pairing is still a chip read from the code, the way ModelChips always
 * drew it; the model half is a select that writes the per-machine policy the
 * dispatcher reads. The choices per runtime come from the server: Claude's
 * fixed aliases, the Codex CLI's configured model, the models Ollama has
 * pulled. "Custom…" takes any name the policy's validator accepts - the
 * runtime CLI, not this control, decides whether it exists. "as coded" (or
 * "inherit" when a runtime-wide default is set) clears the pin.
 *
 * `scope: "all"` is the runtime-wide default at the top of /teams.
 */
export function ModelPicker({
  models,
  scope,
  compact = false,
  choices = EMPTY_CHOICES,
  defaults = {},
}: {
  models: AgentModel[];
  scope: "desk" | "all";
  compact?: boolean;
  choices?: ModelChoices;
  /** The runtime-wide defaults from the policy, so a desk row can say "inherit". */
  defaults?: Partial<Record<string, string | null>>;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [customFor, setCustomFor] = useState<string | null>(null);
  const [customText, setCustomText] = useState("");

  function pick(row: AgentModel, model: string) {
    if (!isModelRuntime(row.runtime)) return;
    if (model === CUSTOM) {
      setCustomFor(`${row.runtime}:${row.model}`);
      setCustomText("");
      return;
    }
    setCustomFor(null);
    setError(null);
    const runtime = row.runtime;
    startTransition(async () => {
      try {
        await setAgentModelAction({
          kinds: scope === "all" ? "*" : row.kinds,
          runtime,
          model: model || null,
        });
        router.refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not change the model.");
      }
    });
  }

  if (!models.length) return null;
  const selectClass = `rounded border border-[var(--border)] bg-[var(--surface)] font-mono text-[10px] text-[var(--ink)] [color-scheme:dark] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent)] ${
    compact ? "px-0.5" : "px-1"
  }`;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {models.map((m) => {
        const runtime = isModelRuntime(m.runtime) ? m.runtime : null;
        const editable = runtime !== null;
        const rowKey = `${m.runtime}:${m.model}`;
        const current = editable && m.pinned ? m.model : "";
        const preset: string[] = runtime ? choices.runtimes[runtime] : [];
        const options = current && !preset.includes(current) ? [current, ...preset] : preset;
        const inherit = defaults[m.runtime] ?? null;
        const codedLabel = m.coded ? `as coded (${m.coded})` : m.runtime === "codex"
          ? "Codex CLI default"
          : "as coded";
        const clearLabel = scope === "all"
          ? codedLabel
          : inherit
            ? `inherit (${MODEL_LABELS[inherit] ?? inherit})`
            : codedLabel;
        const note = runtime ? choices.notes[runtime] : undefined;
        return (
          <span
            key={rowKey}
            title={`${m.kinds.length} job kind${m.kinds.length === 1 ? "" : "s"}: ${m.kinds.join(", ")}${
              m.pinned ? " · set on /teams" : ""
            }${note ? ` · ${note}` : ""}`}
            className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-1.5 py-px font-mono text-[10px] leading-4 text-[var(--ink-3)]"
          >
            {m.pinned ? <Pin className="h-2.5 w-2.5 text-[var(--accent)]" /> : <Cpu className="h-2.5 w-2.5" />}
            <span className="text-[var(--ink-2)]">{m.runtime}</span>
            <span aria-hidden>·</span>
            {editable && customFor === rowKey ? (
              <form
                className="inline-flex items-center gap-1"
                onSubmit={(event) => {
                  event.preventDefault();
                  const name = customText.trim();
                  if (name) pick(m, name);
                }}
              >
                <input
                  autoFocus
                  value={customText}
                  onChange={(event) => setCustomText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") setCustomFor(null);
                  }}
                  placeholder="model name"
                  aria-label={`Custom ${m.runtime} model for ${m.kinds.join(", ")}`}
                  className={`${selectClass} w-28 placeholder:text-[var(--ink-3)]`}
                  disabled={pending}
                />
                <button
                  type="submit"
                  disabled={pending || !customText.trim()}
                  className="text-[10px] text-[var(--accent)] disabled:opacity-50"
                >
                  set
                </button>
                <button
                  type="button"
                  onClick={() => setCustomFor(null)}
                  className="text-[10px] text-[var(--ink-3)]"
                >
                  cancel
                </button>
              </form>
            ) : editable ? (
              <select
                value={current}
                onChange={(event) => pick(m, event.target.value)}
                disabled={pending}
                aria-label={
                  scope === "all"
                    ? `Default ${m.runtime} model for every desk`
                    : `${m.runtime} model for ${m.kinds.join(", ")}`
                }
                className={selectClass}
              >
                <option value="">{clearLabel}</option>
                {options.map((choice) => (
                  <option key={choice} value={choice}>
                    {MODEL_LABELS[choice] ?? choice}
                  </option>
                ))}
                <option value={CUSTOM}>Custom…</option>
              </select>
            ) : (
              <span className="text-[var(--ink)]">{m.model}</span>
            )}
          </span>
        );
      })}
      {error && (
        <span className="text-[10px] text-[var(--red)]" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
