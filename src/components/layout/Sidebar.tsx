"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  ClipboardList,
  Microscope,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { shortcutFor } from "@/lib/navigation";

type NavItem = {
  href: string;
  label: string;
  icon: React.ElementType;
  activePrefixes?: string[];
};

/**
 * Nav grouped by function so the sidebar reads as a map, not a list.
 *
 * The whole PARA/task/inbox system is ONE row ("Planner") whose subpages
 * live in PlannerNav; Research is its own space with its own section nav; the
 * Agent Center keeps only the floor (/teams, /ops, /drafts). Rows are ordered
 * by how often they need your attention: the day, then your own work, then
 * the agent desks, then reference surfaces.
 */
const NAV_GROUPS: { label?: string; items: NavItem[] }[] = [
  {
    label: "Now",
    items: [
      { href: "/today", label: "Today", icon: Sparkles },
      {
        href: "/inbox",
        label: "Planner",
        icon: ClipboardList,
        activePrefixes: [
          "/inbox",
          "/tasks",
          "/projects",
          "/areas",
          "/goals",
          "/notes",
          "/resources",
          "/reviews",
          "/archive",
        ],
      },
    ],
  },
  {
    label: "Desks",
    items: [
      {
        href: "/research/feeds",
        label: "Research",
        icon: Microscope,
        activePrefixes: ["/research"],
      },
      {
        href: "/teams",
        label: "Agent Center",
        icon: Users,
        activePrefixes: ["/teams", "/ops", "/drafts"],
      },
    ],
  },
  {
    label: "System",
    items: [
      {
        href: "/wiki",
        label: "Knowledge",
        icon: BookOpen,
        activePrefixes: ["/wiki", "/vault"],
      },
      { href: "/settings", label: "Diagnostics", icon: Settings },
    ],
  },
];

export function SidebarNav({
  inboxCount,
  reviewCount,
  onNavigate,
}: {
  inboxCount?: number;
  reviewCount?: number;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();

  const isActive = (item: NavItem) =>
    pathname === item.href ||
    pathname.startsWith(`${item.href}/`) ||
    Boolean(item.activePrefixes?.some((prefix) => pathname.startsWith(prefix)));

  return (
    <nav className="flex flex-col gap-4" aria-label="Primary">
      {NAV_GROUPS.map((group, gi) => (
        <div key={group.label ?? gi}>
          {group.label && (
            <div className="mb-1 px-2.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-[var(--ink-3)]">
              {group.label}
            </div>
          )}
          <div className="flex flex-col gap-0.5">
            {group.items.map((item) => {
              const { href, label, icon: Icon } = item;
              const active = isActive(item);
              const shortcut = shortcutFor(href);
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group relative flex items-center gap-2.5 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-sm transition-colors",
                    active
                      ? "bg-[var(--accent-soft)] font-medium text-[var(--accent-ink)]"
                      : "text-[var(--ink-2)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)]"
                  )}
                >
                  {active && (
                    <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-[var(--accent)] shadow-[var(--glow-accent)]" />
                  )}
                  <Icon className="h-4 w-4 shrink-0" strokeWidth={active ? 2.4 : 2} />
                  <span className="flex-1">{label}</span>
                  {label === "Planner" && inboxCount ? (
                    <span className="rounded-full bg-[var(--accent)] px-1.5 py-px text-[10px] font-semibold text-white tabular-nums shadow-[var(--glow-accent)]">
                      {inboxCount}
                    </span>
                  ) : label === "Agent Center" && reviewCount ? (
                    <span
                      className="min-w-5 rounded-full bg-[var(--amber)] px-1.5 py-px text-center text-[10px] font-semibold text-white tabular-nums"
                      title={`${reviewCount} completed job${reviewCount === 1 ? "" : "s"} awaiting review`}
                      aria-label={`${reviewCount} jobs awaiting review`}
                    >
                      {reviewCount > 99 ? "99+" : reviewCount}
                    </span>
                  ) : shortcut ? (
                    <kbd className="hidden group-hover:inline">g {shortcut}</kbd>
                  ) : null}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}
