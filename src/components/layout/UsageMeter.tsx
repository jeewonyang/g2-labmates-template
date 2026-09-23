"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Gauge, RefreshCw } from "lucide-react";
import type { LimitProvider, LimitWindow, UsageLimits } from "@/lib/services/limits";

/**
 * Header usage board: how much Claude and Codex subscription capacity is left
 * and when each window resets.
 *
 * Polls slowly (the numbers move at the speed of your own usage, not the
 * network) and counts the reset down locally so the clock ticks without a
 * request behind it.
 */

const POLL_MS = 120_000;

/** Remaining-capacity thresholds. Below 15% is the "stop and plan" zone. */
function tone(remaining: number): { color: string; text: string } {
  if (remaining <= 15) return { color: "var(--red)", text: "text-[var(--red)]" };
  if (remaining <= 35) return { color: "var(--amber)", text: "text-[var(--amber)]" };
  return { color: "var(--green)", text: "text-[var(--green)]" };
}

function countdown(iso: string | null, nowMs: number): string {
  if (!iso) return "reset time unknown";
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "reset time unknown";
  let secs = Math.floor((at - nowMs) / 1000);
  if (secs <= 0) return "resetting now";
  const days = Math.floor(secs / 86400);
  secs -= days * 86400;
  const hours = Math.floor(secs / 3600);
  secs -= hours * 3600;
  const mins = Math.floor(secs / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m ${secs - mins * 60}s`;
}

function agoLabel(iso: string | null, nowMs: number): string {
  if (!iso) return "unknown";
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "unknown";
  const mins = Math.floor(Math.max(0, nowMs - at) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** Lowest remaining window across every provider — what the collapsed pill shows. */
function tightest(limits: UsageLimits | null): LimitWindow | null {
  if (!limits) return null;
  let best: LimitWindow | null = null;
  for (const provider of limits.providers) {
    if (!provider.ok) continue;
    for (const window of provider.windows) {
      if (!best || window.remaining_percent < best.remaining_percent) best = window;
    }
  }
  return best;
}

export function UsageMeter() {
  const [limits, setLimits] = useState<UsageLimits | null>(null);
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const rootRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async (force = false) => {
    setRefreshing(true);
    try {
      const res = await fetch(`/api/usage-limits${force ? "?force=1" : ""}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(String(res.status));
      setLimits((await res.json()) as UsageLimits);
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  // Drives the reset countdowns. Only runs while the panel is open — a 1s
  // interval behind a closed panel would re-render the header all day.
  useEffect(() => {
    if (!open) return;
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const lowest = tightest(limits);
  const pill = lowest ? tone(lowest.remaining_percent) : null;

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={
          lowest
            ? `Usage limits: ${lowest.remaining_percent}% remaining on ${lowest.label}`
            : "Usage limits"
        }
        className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-sm)] border bg-[var(--surface)] px-2.5 text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-hover)]"
      >
        <Gauge className="h-4 w-4" />
        {lowest ? (
          <span className={`font-mono text-xs font-semibold tabular-nums ${pill?.text ?? ""}`}>
            {Math.round(lowest.remaining_percent)}%
          </span>
        ) : (
          <span className="font-mono text-xs text-[var(--ink-3)]">
            {failed ? "n/a" : "··"}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Subscription usage limits"
          className="absolute right-0 top-full z-40 mt-2 w-[19rem] rounded-[var(--radius-sm)] border bg-[var(--surface)] p-3 shadow-[var(--shadow-md)]"
        >
          <div className="mb-2.5 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-[var(--ink)]">Usage remaining</h2>
            <button
              onClick={() => void load(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--ink-3)] transition-colors hover:bg-[var(--surface-hover)] disabled:opacity-50"
            >
              <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
              refresh
            </button>
          </div>

          {!limits || limits.providers.length === 0 ? (
            <p className="text-xs text-[var(--ink-3)]">
              {failed || limits?.refreshError
                ? limits?.refreshError ?? "Could not read usage limits."
                : "Reading limits…"}
            </p>
          ) : (
            <div className="space-y-3">
              {limits.providers.map((provider) => (
                <ProviderBlock key={provider.key} provider={provider} nowMs={nowMs} />
              ))}
            </div>
          )}

          {limits && (
            <p className="mt-3 border-t border-[var(--border)] pt-2 text-[10px] text-[var(--ink-3)]">
              Checked {agoLabel(limits.generated_at, nowMs)}
              {limits.refreshError ? ` · ${limits.refreshError}` : ""}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ProviderBlock({ provider, nowMs }: { provider: LimitProvider; nowMs: number }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-xs font-semibold text-[var(--ink)]">{provider.label}</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--ink-3)]">
          {provider.freshness === "snapshot"
            ? `as of ${agoLabel(provider.observed_at, nowMs)}`
            : "live"}
        </span>
      </div>

      {!provider.ok ? (
        <p className="text-[11px] text-[var(--ink-3)]">{provider.error ?? "unavailable"}</p>
      ) : (
        <ul className="space-y-2">
          {provider.windows.map((window) => {
            const t = tone(window.remaining_percent);
            return (
              <li key={window.id}>
                <div className="flex items-baseline justify-between gap-2 text-[11px]">
                  <span className="text-[var(--ink-2)]">{window.label}</span>
                  <span className={`font-mono font-semibold tabular-nums ${t.text}`}>
                    {Math.round(window.remaining_percent)}% left
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--surface-2)]">
                  <div
                    className="h-full rounded-full transition-[width] duration-500"
                    style={{
                      width: `${Math.max(2, window.remaining_percent)}%`,
                      backgroundColor: t.color,
                    }}
                  />
                </div>
                <p className="mt-0.5 font-mono text-[10px] text-[var(--ink-3)]">
                  resets in {countdown(window.resets_at, nowMs)}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
