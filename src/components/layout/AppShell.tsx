"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Menu, Plus, Search, X } from "lucide-react";
import { SidebarNav } from "@/components/layout/Sidebar";
import { Clock } from "@/components/layout/Clock";
import { UsageMeter } from "@/components/layout/UsageMeter";
import { QuickCapture } from "@/components/capture/QuickCapture";
import { CommandPalette } from "@/components/command/CommandPalette";
import { GOTO_SHORTCUTS } from "@/lib/navigation";
import { AgentActivityCenter } from "@/components/activity/AgentActivityCenter";
import { G2Mark } from "@/components/brand/G2Mark";


function isTypingTarget(el: EventTarget | null): boolean {
  const node = el as HTMLElement | null;
  if (!node) return false;
  const tag = node.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || node.isContentEditable;
}

export function AppShell({
  children,
  inboxCount,
  reviewCount,
  pipelineHealth,
}: {
  children: React.ReactNode;
  inboxCount: number;
  reviewCount: number;
  pipelineHealth: {
    label: string;
    tone: "healthy" | "working" | "attention" | "local";
  };
}) {
  const router = useRouter();
  const [captureOpen, setCaptureOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [awaitingGoto, setAwaitingGoto] = useState(false);

  const openCapture = useCallback(() => setCaptureOpen(true), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;

      // Quick capture: "c", or Ctrl/Cmd+Shift+Space from anywhere.
      if (!e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === "c") {
        e.preventDefault();
        setCaptureOpen(true);
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === "Space") {
        e.preventDefault();
        setCaptureOpen(true);
        return;
      }

      // "g" then a letter → navigate.
      if (awaitingGoto && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const dest = GOTO_SHORTCUTS[e.key.toLowerCase()];
        setAwaitingGoto(false);
        if (dest) {
          e.preventDefault();
          router.push(dest);
        }
        return;
      }
      if (!e.metaKey && !e.ctrlKey && !e.altKey && e.key.toLowerCase() === "g") {
        setAwaitingGoto(true);
        setTimeout(() => setAwaitingGoto(false), 1200);
        return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [awaitingGoto, router]);

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r bg-[var(--surface)]/70 px-3 py-4 backdrop-blur lg:flex">
        <Brand health={pipelineHealth} />
        <div className="mt-5 flex-1 overflow-y-auto">
          <SidebarNav inboxCount={inboxCount} reviewCount={reviewCount} />
        </div>
        <ShortcutHint />
      </aside>

      {/* Mobile drawer */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setMobileNavOpen(false)}>
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
          <aside
            className="animate-in absolute inset-y-0 left-0 flex w-64 flex-col border-r bg-[var(--surface)] px-3 py-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <Brand health={pipelineHealth} />
              <button
                onClick={() => setMobileNavOpen(false)}
                aria-label="Close menu"
                className="rounded p-1 text-[var(--ink-3)] hover:bg-[var(--surface-hover)]"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-5 flex-1 overflow-y-auto">
              <SidebarNav
                inboxCount={inboxCount}
                reviewCount={reviewCount}
                onNavigate={() => setMobileNavOpen(false)}
              />
            </div>
          </aside>
        </div>
      )}

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col lg:pl-60">
        <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-[var(--bg)]/70 px-4 py-2.5 backdrop-blur-md">
          <button
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open menu"
            className="rounded p-1.5 text-[var(--ink-2)] hover:bg-[var(--surface-hover)] lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>

          <button
            onClick={() => {
              // Dispatch Cmd+K so the palette (which owns its own state) opens.
              window.dispatchEvent(
                new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true })
              );
            }}
            className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-[var(--radius-sm)] border bg-[var(--surface)] px-3 text-sm text-[var(--ink-3)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--surface-hover)] sm:max-w-md"
          >
            <Search className="h-4 w-4 shrink-0" />
            {/* Truncates rather than wraps: the button is a fixed h-9, so a
                second line would render outside its border. */}
            <span className="min-w-0 flex-1 truncate text-left">
              <span className="sm:hidden">Search</span>
              <span className="hidden sm:inline">Search or jump to…</span>
            </span>
            <kbd className="hidden shrink-0 sm:inline">⌘K</kbd>
          </button>

          {/* Only pushes the right-hand controls over once the search bar is
              capped (sm+). On phones it would compete with it for free space. */}
          <div className="hidden flex-1 sm:block" />

          <AgentActivityCenter />

          <button
            onClick={openCapture}
            aria-label="Capture a thought"
            className="inline-flex h-9 items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 text-sm font-medium text-white shadow-[var(--glow-accent)] transition-opacity hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            <span className="hidden sm:inline">Capture</span>
          </button>

          <UsageMeter />

          <Clock />
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">{children}</main>
      </div>

      <QuickCapture open={captureOpen} onClose={() => setCaptureOpen(false)} />
      <CommandPalette onCapture={openCapture} />
    </div>
  );
}

function Brand({
  health,
}: {
  health: { label: string; tone: "healthy" | "working" | "attention" | "local" };
}) {
  const dot =
    health.tone === "healthy"
      ? "bg-[var(--green)]"
      : health.tone === "attention"
        ? "bg-[var(--amber)]"
        : health.tone === "working"
          ? "bg-[var(--accent)]"
          : "bg-[var(--ink-3)]";
  return (
    <Link href="/" className="flex items-center gap-2.5 px-1.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--accent)] to-[#4338ca] text-white shadow-[var(--glow-accent)]">
        <G2Mark className="h-5 w-5" />
      </span>
      <span className="flex flex-col leading-tight">
        <span className="text-sm font-semibold tracking-tight text-[var(--ink)]">G2</span>
        <span className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.16em] text-[var(--ink-3)]">
          <span className={`status-dot h-1.5 w-1.5 rounded-full ${dot}`} />
          {health.label}
        </span>
      </span>
    </Link>
  );
}

function ShortcutHint() {
  return (
    <div className="mt-2 space-y-1.5 border-t px-2 pt-3 text-[11px] text-[var(--ink-3)]">
      <div className="flex items-center justify-between"><span>Capture</span><kbd>c</kbd></div>
      <div className="flex items-center justify-between"><span>Command</span><kbd>⌘K</kbd></div>
      <div className="flex items-center justify-between"><span>Go to…</span><kbd>g then h/t/p…</kbd></div>
    </div>
  );
}
