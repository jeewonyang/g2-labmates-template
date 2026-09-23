"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import {
  CheckCircle2,
  Code2,
  Inbox,
  Loader2,
  Sparkles,
  WandSparkles,
  X,
} from "lucide-react";
import {
  cancelG2AgentRunAction,
  captureAction,
  getG2AgentRunAction,
  getRecentG2AgentRunsAction,
  launchG2AgentAction,
} from "@/lib/actions";
import { INBOX_ITEM_TYPES, type InboxItemType } from "@/lib/types";
import type {
  G2AgentProvider,
  G2AgentRun,
} from "@/lib/services/g2-agent";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

const TYPE_LABEL: Record<InboxItemType, string> = {
  task: "Task",
  note: "Note",
  resource: "Resource",
  idea: "Idea",
  journal: "Journal",
  unknown: "Auto",
};

/**
 * Quick capture dialog. Opened from the topbar button, the "c" shortcut, or
 * Ctrl/Cmd+Shift+Space. Writes through the same captureAction the REST API
 * uses, so web captures behave identically to future iOS captures.
 */
export function QuickCapture({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [type, setType] = useState<InboxItemType>("unknown");
  const [destination, setDestination] = useState<"automatic" | "manual" | "agent">("automatic");
  const [provider, setProvider] = useState<G2AgentProvider>("codex");
  const [activeRun, setActiveRun] = useState<G2AgentRun | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, startTransition] = useTransition();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      returnFocusRef.current = document.activeElement as HTMLElement | null;
      setSaved(false);
      const savedProvider = window.localStorage.getItem("g2-agent-provider");
      if (savedProvider === "codex" || savedProvider === "claude") {
        setProvider(savedProvider);
      }
      // Focus after the dialog paints.
      const id = setTimeout(() => textareaRef.current?.focus(), 30);
      return () => {
        clearTimeout(id);
        returnFocusRef.current?.focus();
      };
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), textarea:not([disabled]), select:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        );
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || activeRun) return;
    let cancelled = false;
    void getRecentG2AgentRunsAction()
      .then(([run]) => {
        if (!cancelled && run) setActiveRun(run);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [activeRun, open]);

  useEffect(() => {
    if (
      !activeRun ||
      !["queued", "running", "cancel_requested"].includes(activeRun.status)
    ) {
      return;
    }
    let cancelled = false;
    const id = window.setTimeout(() => {
      void getG2AgentRunAction(activeRun.id)
        .then((run) => {
          if (!cancelled && run) setActiveRun(run);
        })
        .catch(() => undefined);
    }, 2_000);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [activeRun]);

  if (!open) return null;

  const submit = () => {
    if (!text.trim() || pending) return;
    startTransition(async () => {
      try {
        setSubmitError(null);
        if (destination === "agent") {
          const run = await launchG2AgentAction({
            clientRequestId: window.crypto.randomUUID(),
            prompt: text.trim(),
            provider,
          });
          setActiveRun(run);
          setText("");
        } else {
          await captureAction({
            rawText: text.trim(),
            type,
            automationMode: destination,
          });
          setText("");
          setType("unknown");
          setSaved(true);
          setTimeout(() => setSaved(false), 1800);
        }
        textareaRef.current?.focus();
      } catch (error) {
        setSubmitError(
          error instanceof Error ? error.message : "The request could not be started.",
        );
      }
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 px-3 pb-4 pt-3 backdrop-blur-sm sm:px-4 sm:pt-[12vh]"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Quick capture"
    >
      <div
        ref={dialogRef}
        className="animate-in w-full max-w-2xl rounded-[var(--radius-card)] border bg-[var(--surface)] shadow-[var(--shadow-md)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-4 py-2.5">
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--ink)]">
            <Sparkles className="h-4 w-4 text-[var(--accent)]" />
            Quick capture
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-[var(--ink-3)] hover:bg-[var(--surface-hover)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-4">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                submit();
              }
            }}
            rows={4}
            placeholder={
              destination === "agent"
                ? "Describe what G2 should add or fix…"
                : "Capture a thought, task, link, or idea… it lands in your Inbox."
            }
            className="w-full resize-y rounded-[var(--radius-sm)] border bg-[var(--surface)] px-3 py-2 text-sm text-[var(--ink)] placeholder:text-[var(--ink-3)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
          />

          {/* The submit row sits directly under the text, not in a footer
              (2026-09-21): on a phone the open keyboard covered a footer below
              the destination cards and the agent panel, so Launch could not be
              pressed. Here it stays next to what they just typed. */}
          <div className="mt-2 flex items-center justify-between gap-3">
            <span className="min-w-0 text-xs text-[var(--ink-3)]">
              {saved ? (
                <span className="text-[var(--green)]">Saved to Inbox ✓</span>
              ) : destination === "agent" ? (
                <span>Explicit launch only — captures are never auto-routed to code agents.</span>
              ) : (
                <span className="hidden sm:inline">
                  <kbd className="font-mono">⌘/Ctrl</kbd> + <kbd className="font-mono">Enter</kbd> to save
                </span>
              )}
            </span>
            <Button
              variant="primary"
              size="sm"
              onClick={submit}
              disabled={!text.trim() || pending}
              className="shrink-0"
            >
              {pending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {destination === "agent"
                ? `Launch ${provider === "codex" ? "Codex" : "Claude"}`
                : "Capture"}
            </Button>
          </div>

          {destination !== "agent" && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {INBOX_ITEM_TYPES.map((t) => (
                <button
                  key={t}
                  onClick={() => setType(t)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                    type === t
                      ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent-ink)]"
                      : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]"
                  )}
                >
                  {TYPE_LABEL[t]}
                </button>
              ))}
            </div>
          )}

          <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
            <button
              type="button"
              onClick={() => setDestination("automatic")}
              aria-pressed={destination === "automatic"}
              className={cn(
                "flex min-w-0 items-start gap-2 rounded-[var(--radius-sm)] border p-2.5 text-left transition-colors",
                destination === "automatic"
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "hover:bg-[var(--surface-hover)]",
              )}
            >
              <WandSparkles className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent)]" />
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-[var(--ink)]">
                  Auto organize
                </span>
                <span className="block text-[11px] leading-4 text-[var(--ink-3)]">
                  Local triage, independent verification, then safe filing and task creation.
                </span>
              </span>
            </button>
            <button
              type="button"
              onClick={() => setDestination("manual")}
              aria-pressed={destination === "manual"}
              className={cn(
                "flex min-w-0 items-start gap-2 rounded-[var(--radius-sm)] border p-2.5 text-left transition-colors",
                destination === "manual"
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "hover:bg-[var(--surface-hover)]",
              )}
            >
              <Inbox className="mt-0.5 h-4 w-4 shrink-0 text-[var(--ink-2)]" />
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-[var(--ink)]">
                  Keep for me
                </span>
                <span className="block text-[11px] leading-4 text-[var(--ink-3)]">
                  Leave it in Inbox and choose Task, Note, or Resource yourself.
                </span>
              </span>
            </button>
            <button
              type="button"
              onClick={() => setDestination("agent")}
              aria-pressed={destination === "agent"}
              className={cn(
                "flex min-w-0 items-start gap-2 rounded-[var(--radius-sm)] border p-2.5 text-left transition-colors",
                destination === "agent"
                  ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                  : "hover:bg-[var(--surface-hover)]",
              )}
            >
              <Code2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent)]" />
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-[var(--ink)]">
                  Build / fix G2
                </span>
                <span className="block text-[11px] leading-4 text-[var(--ink-3)]">
                  Launch a coding agent on this G2 repo to judge and implement it.
                </span>
              </span>
            </button>
          </div>

          {destination === "agent" && (
            <div className="mt-3 rounded-[var(--radius-sm)] border bg-[var(--surface-2)] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-xs font-semibold text-[var(--ink)]">
                  Coding agent
                </div>
                <div className="flex rounded-full border bg-[var(--surface)] p-0.5">
                  {(["codex", "claude"] as const).map((candidate) => (
                    <button
                      key={candidate}
                      type="button"
                      onClick={() => {
                        setProvider(candidate);
                        window.localStorage.setItem("g2-agent-provider", candidate);
                      }}
                      aria-pressed={provider === candidate}
                      className={cn(
                        "rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize",
                        provider === candidate
                          ? "bg-[var(--accent)] text-white"
                          : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)]",
                      )}
                    >
                      {candidate}
                    </button>
                  ))}
                </div>
              </div>
              <p className="mt-2 text-[11px] leading-4 text-[var(--ink-3)]">
                Runs in the background against the fixed G2 working tree. Project
                hooks stay active, private vault source is excluded, and unrelated
                edits must be preserved. Codex is the default for code changes.
              </p>

              {activeRun && (
                <div className="mt-3 border-t pt-3" aria-live="polite">
                  <div className="flex items-center gap-2 text-xs font-semibold text-[var(--ink)]">
                    {activeRun.status === "completed" ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-[var(--green)]" />
                    ) : ["failed", "cancelled"].includes(activeRun.status) ? (
                      <X className="h-3.5 w-3.5 text-[var(--red)]" />
                    ) : (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--accent)]" />
                    )}
                    <span className="capitalize">{activeRun.provider}</span>
                    <span className="font-normal text-[var(--ink-3)]">
                      {activeRun.status === "queued"
                        ? "queued"
                        : activeRun.status === "cancel_requested"
                          ? "stopping"
                        : activeRun.status === "running"
                          ? activeRun.phase === "verifying"
                            ? "validating changes"
                            : "working"
                          : activeRun.status}
                    </span>
                  </div>
                  {(activeRun.error || activeRun.result) && (
                    <div className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap rounded border bg-[var(--surface)] p-2 text-[11px] leading-4 text-[var(--ink-2)]">
                      {activeRun.error || activeRun.result}
                    </div>
                  )}
                  {activeRun.changedFiles && activeRun.changedFiles.length > 0 && (
                    <div className="mt-2 text-[10px] leading-4 text-[var(--ink-3)]">
                      <span className="font-semibold text-[var(--ink-2)]">
                        Newly changed:
                      </span>{" "}
                      {activeRun.changedFiles.join(", ")}
                    </div>
                  )}
                  {activeRun.checks && activeRun.checks.length > 0 && (
                    <div className="mt-1 text-[10px] leading-4 text-[var(--ink-3)]">
                      {activeRun.checks.map((check) => (
                        <div key={check.name}>
                          {check.ok ? "✓" : "×"} {check.name}
                        </div>
                      ))}
                    </div>
                  )}
                  {["queued", "running", "cancel_requested"].includes(
                    activeRun.status,
                  ) && (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <p className="text-[10px] text-[var(--ink-3)]">
                        You can close Quick Capture and monitor this in Queue &amp; review.
                      </p>
                      <button
                        type="button"
                        disabled={pending || activeRun.status === "cancel_requested"}
                        onClick={() => {
                          if (!window.confirm("Stop this coding-agent run?")) return;
                          startTransition(async () => {
                            try {
                              setActiveRun(
                                await cancelG2AgentRunAction(activeRun.id),
                              );
                            } catch (error) {
                              setSubmitError(
                                error instanceof Error
                                  ? error.message
                                  : "The run could not be stopped.",
                              );
                            }
                          });
                        }}
                        className="text-[10px] font-semibold text-red-700 hover:underline disabled:opacity-50 dark:text-red-300"
                      >
                        {activeRun.status === "cancel_requested"
                          ? "Stopping…"
                          : "Stop run"}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {submitError && (
            <p className="mt-3 text-xs text-[var(--red)]" role="alert">
              {submitError}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
