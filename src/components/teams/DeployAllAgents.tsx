"use client";

import { useCallback, useEffect, useState } from "react";
import { Bot, Check, Loader2, Play, TriangleAlert } from "lucide-react";

type DeployState = {
  status: "idle" | "running" | "completed" | "failed";
  startedAt?: string | null;
  finishedAt?: string | null;
  output?: string;
  queue?: Record<string, number>;
};

export function DeployAllAgents() {
  const [state, setState] = useState<DeployState>({ status: "idle" });
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const res = await fetch("/api/agents", { cache: "no-store" });
    if (!res.ok) return;
    setState((await res.json()) as DeployState);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (state.status !== "running" && !starting) return;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [refresh, starting, state.status]);

  async function deploy() {
    setStarting(true);
    setError(null);
    try {
      const res = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "deploy-all" }),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body.error ?? "Could not deploy agents.");
        if (body.state) setState(body.state);
      } else {
        setState({ status: "running", startedAt: new Date().toISOString() });
      }
    } catch (cause) {
      setError(String(cause));
    } finally {
      setStarting(false);
    }
  }

  const running = starting || state.status === "running";
  const Icon =
    running
      ? Loader2
      : state.status === "completed"
        ? Check
        : state.status === "failed"
          ? TriangleAlert
          : Play;

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        onClick={deploy}
        disabled={running}
        aria-pressed={running}
        className="inline-flex h-9 items-center gap-2 rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 text-sm font-medium text-white shadow-[var(--glow-accent)] transition-opacity hover:opacity-90 disabled:opacity-70"
      >
        <span
          className={`relative h-4 w-7 rounded-full border border-white/40 ${
            running ? "bg-white/35" : "bg-black/15"
          }`}
          aria-hidden="true"
        >
          <span
            className={`absolute top-0.5 h-2.5 w-2.5 rounded-full bg-white transition-all ${
              running ? "left-3.5" : "left-0.5"
            }`}
          />
        </span>
        <Icon className={`h-4 w-4 ${running ? "animate-spin" : ""}`} />
        {running ? "All agents working" : "Deploy all agents"}
      </button>
      <span className="flex items-center gap-1 text-[10px] text-[var(--ink-3)]">
        <Bot className="h-3 w-3" />
        {error
          ? error
          : state.status === "completed"
            ? `Last run completed${
                state.finishedAt
                  ? ` · ${new Date(state.finishedAt).toLocaleTimeString([], {
                      hour: "numeric",
                      minute: "2-digit",
                    })}`
                  : ""
              }`
            : state.status === "failed"
              ? "Last run failed — details are in Agent OS"
              : "Runs every enabled team once"}
      </span>
    </div>
  );
}
