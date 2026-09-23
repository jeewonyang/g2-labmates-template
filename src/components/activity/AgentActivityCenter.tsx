"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Bell,
  Bot,
  Check,
  ChevronRight,
  ListChecks,
  Mail,
  X,
} from "lucide-react";
import type {
  AgentActivityItem,
  AgentActivityTone,
} from "@/lib/services/activity";

const ICONS = {
  task: ListChecks,
  draft: Mail,
  job: Bot,
  automation: Bot,
} as const;

const TONES: Record<AgentActivityTone, string> = {
  info: "bg-[var(--accent-soft)] text-[var(--accent-ink)]",
  success: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  attention: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  error: "bg-red-500/10 text-red-600 dark:text-red-400",
};

function relative(iso: string): string {
  const diff = Math.max(0, Date.now() - Date.parse(iso));
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function AgentActivityCenter() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AgentActivityItem[]>([]);
  const [lastSeen, setLastSeen] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);

  const refresh = useCallback(async (since?: string) => {
    const query = since ? `?since=${encodeURIComponent(since)}` : "";
    const res = await fetch(`/api/activity${query}`, {
      cache: "no-store",
    });
    if (!res.ok) return;
    const data = (await res.json()) as {
      since?: string;
      items?: AgentActivityItem[];
    };
    setItems(Array.isArray(data.items) ? data.items : []);
    if (data.since) setLastSeen(data.since);
  }, []);

  useEffect(() => {
    setMounted(true);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!lastSeen) return;
    const timer = window.setInterval(() => void refresh(lastSeen), 60_000);
    return () => window.clearInterval(timer);
  }, [lastSeen, refresh]);

  useEffect(() => {
    if (!open) return;
    const opener = openerRef.current;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
      if (event.key === "Tab" && dialogRef.current) {
        const focusable = [
          ...dialogRef.current.querySelectorAll<HTMLElement>(
            'a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])',
          ),
        ];
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [open]);

  async function markSeen() {
    const res = await fetch("/api/activity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "mark-seen" }),
    });
    if (!res.ok) return;
    const body = (await res.json()) as { seenAt?: string };
    setLastSeen(body.seenAt ?? new Date().toISOString());
    setItems([]);
    setOpen(false);
  }

  const count = items.length;

  return (
    <>
      <button
        ref={openerRef}
        onClick={() => setOpen(true)}
        aria-label={
          count ? `${count} unseen agent changes` : "Agent change notifications"
        }
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-[var(--radius-sm)] border bg-[var(--surface)] text-[var(--ink-2)] transition-colors hover:bg-[var(--surface-hover)]"
      >
        <Bell className="h-4 w-4" />
        {count > 0 && (
          <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-[var(--amber)] px-1 text-center font-mono text-[9px] font-bold leading-4 text-black">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>

      {mounted &&
        createPortal(
          <>
      {/*
        No floating toast. The badge on the bell already says how many things
        need you, and a second copy of the same list pinned over the page was
        redundant — two surfaces reporting one fact. The bell is the signal;
        this drawer is the detail.
      */}
      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <section
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Agent changes"
            className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l bg-[var(--surface)] shadow-[var(--shadow-lg)]"
            style={{ height: "100dvh", minHeight: "100vh" }}
          >
            <div className="flex items-center justify-between border-b px-4 py-3">
              <div>
                <h2 className="font-semibold text-[var(--ink)]">Agent changes</h2>
                <p className="text-xs text-[var(--ink-3)]">
                  Since {lastSeen ? new Date(lastSeen).toLocaleString() : "your last check"}
                </p>
              </div>
              <button
                ref={closeRef}
                onClick={() => setOpen(false)}
                aria-label="Close agent changes"
                className="rounded p-1.5 text-[var(--ink-3)] hover:bg-[var(--surface-hover)]"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {count === 0 ? (
                <div className="flex h-full flex-col items-center justify-center px-8 text-center">
                  <Check className="mb-3 h-8 w-8 text-[var(--green)]" />
                  <p className="font-medium text-[var(--ink)]">You are caught up</p>
                  <p className="mt-1 text-sm text-[var(--ink-3)]">
                    Only things that need you land here: jobs awaiting your
                    decision, failures, new drafts and tasks, and captures G2
                    filed on its own. Watch live progress on /ops.
                  </p>
                </div>
              ) : (
                <ul className="space-y-2">
                  {items.map((item) => {
                    const Icon = ICONS[item.category];
                    return (
                      <li key={item.id}>
                        <Link
                          href={item.href}
                          onClick={() => setOpen(false)}
                          className="flex items-start gap-3 rounded-[var(--radius-sm)] border p-3 transition-colors hover:bg-[var(--surface-hover)]"
                        >
                          <span className={`rounded-full p-2 ${TONES[item.tone]}`}>
                            <Icon className="h-4 w-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block text-sm font-medium text-[var(--ink)]">
                              {item.title}
                            </span>
                            <span className="mt-0.5 block text-xs text-[var(--ink-3)]">
                              {item.detail}
                            </span>
                            <span className="mt-1 block font-mono text-[10px] text-[var(--ink-3)]">
                              {relative(item.at)}
                            </span>
                          </span>
                          <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-[var(--ink-3)]" />
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            {count > 0 && (
              <div className="border-t p-3">
                <button
                  onClick={markSeen}
                  className="w-full rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white"
                >
                  Mark all as seen
                </button>
              </div>
            )}
          </section>
        </div>
      )}
          </>,
          document.body,
        )}
    </>
  );
}
