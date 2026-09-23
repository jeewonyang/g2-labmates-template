"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Archive,
  BookOpen,
  Bot,
  CalendarCheck,
  CheckSquare,
  ClipboardList,
  FileText,
  FlaskConical,
  FolderKanban,
  FolderOpen,
  Inbox,
  Layers,
  LayoutGrid,
  ListChecks,
  Mail,
  Microscope,
  Newspaper,
  NotebookPen,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";

type SectionItem = {
  href: string;
  label: string;
  icon: React.ElementType;
  prefixes?: string[];
  /** Match only the exact path — for a parent route with sibling subpages. */
  exact?: boolean;
};

/**
 * One section nav per space: the PARA/task/inbox system is one sidebar row
 * with these subpages; Research is its own space; the Agent Center keeps only the floor itself. A page belongs to
 * exactly one nav — the same destination never appears in two.
 */
const PLANNER_ITEMS: SectionItem[] = [
  { href: "/inbox", label: "Inbox", icon: Inbox },
  { href: "/tasks", label: "Tasks", icon: CheckSquare },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/areas", label: "Areas & goals", icon: LayoutGrid, prefixes: ["/goals"] },
  { href: "/notes", label: "Notes", icon: NotebookPen },
  { href: "/resources", label: "Resources", icon: Layers },
  { href: "/reviews", label: "Reviews", icon: CalendarCheck },
  { href: "/archive", label: "Archive", icon: Archive },
];

const RESEARCH_ITEMS: SectionItem[] = [
  { href: "/research/feeds", label: "Newsletters", icon: Newspaper },
  // Exact: "/research" would otherwise stay lit on both subpages.
  { href: "/research", label: "Library", icon: BookOpen, exact: true },
  { href: "/research/digests", label: "Digests", icon: FileText },
  { href: "/research/notebook", label: "Lab notebook", icon: FlaskConical },
];

const AGENT_ITEMS: SectionItem[] = [
  { href: "/teams", label: "Overview", icon: Users },
  { href: "/ops", label: "Queue & review", icon: ListChecks },
  { href: "/drafts", label: "Drafts", icon: Mail },
];

const KNOWLEDGE_ITEMS: SectionItem[] = [
  { href: "/wiki", label: "Wiki", icon: BookOpen },
  { href: "/vault", label: "Memory", icon: FolderOpen },
];

export function PlannerNav() {
  return <SectionNav label="Planner" icon={ClipboardList} items={PLANNER_ITEMS} />;
}

export function ResearchNav() {
  return <SectionNav label="Research" icon={Microscope} items={RESEARCH_ITEMS} />;
}

export function AgentCenterNav() {
  return <SectionNav label="Agent Center" icon={Bot} items={AGENT_ITEMS} />;
}

export function KnowledgeNav() {
  return <SectionNav label="Knowledge" icon={FileText} items={KNOWLEDGE_ITEMS} />;
}

function SectionNav({
  label,
  icon: Icon,
  items,
}: {
  label: string;
  icon: React.ElementType;
  items: SectionItem[];
}) {
  const pathname = usePathname();
  return (
    <div className="mb-5 flex min-w-0 flex-wrap items-center gap-1 rounded-[var(--radius-card)] border bg-[var(--surface)] p-1 shadow-[var(--shadow-sm)]">
      <span className="mr-1 flex items-center gap-1.5 px-2 text-xs font-semibold text-[var(--ink-2)]">
        <Icon className="h-3.5 w-3.5 text-[var(--accent)]" />
        {label}
      </span>
      {items.map((item) => {
        const active = item.exact
          ? pathname === item.href ||
            Boolean(item.prefixes?.some((prefix) => pathname.startsWith(prefix)))
          : pathname === item.href ||
            pathname.startsWith(`${item.href}/`) ||
            item.prefixes?.some((prefix) => pathname.startsWith(prefix));
        const ItemIcon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-1.5 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs font-medium transition-colors",
              active
                ? "bg-[var(--accent-soft)] text-[var(--accent-ink)]"
                : "text-[var(--ink-3)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)]",
            )}
          >
            <ItemIcon className="h-3.5 w-3.5" />
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}
