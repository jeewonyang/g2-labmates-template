import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { NotebookBadges } from "@/components/research/NotebookBadges";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/primitives";
import type { NotebookEntrySummary } from "@/lib/services/labNotebook";

/** The entry rows, one drawing for the notebook and its archive. */
export function NotebookEntryList({
  entries,
  empty,
  showWhy = false,
  projectStatus = {},
}: {
  entries: NotebookEntrySummary[];
  empty: { title: string; description: string };
  /** On the archive: say whether a row was archived by hand or by its project's status. */
  showWhy?: boolean;
  projectStatus?: Record<string, string>;
}) {
  if (!entries.length) {
    return (
      <EmptyState
        icon={<FlaskConical className="h-6 w-6" />}
        title={empty.title}
        description={empty.description}
      />
    );
  }
  return (
    <ul className="divide-y">
      {entries.map((e) => (
        <li key={`${e.projectCode}/${e.name}`} className="py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/research/notebook/${e.projectCode}/${e.name}`}
              className="font-mono text-sm font-medium text-[var(--ink)] hover:text-[var(--accent-ink)] hover:underline"
            >
              {e.name}
            </Link>
            {e.label && <span className="min-w-0 truncate text-sm text-[var(--ink-2)]">{e.label}</span>}
            <span className="ml-auto flex items-center gap-1.5">
              {e.source === "onenote" && <Badge tone="blue">OneNote</Badge>}
              {e.loggedBy === "auto" && <Badge tone="purple">Auto</Badge>}
              {showWhy && <Badge>project {projectStatus[e.projectCode] ?? "not in planner"}</Badge>}
              <NotebookBadges assay={e.assay} outcome={e.outcome} status={e.status} />
            </span>
          </div>
          {e.summary && <p className="mt-1 line-clamp-2 text-xs text-[var(--ink-2)]">{e.summary}</p>}
        </li>
      ))}
    </ul>
  );
}
