import Link from "next/link";
import { ResearchNav } from "@/components/layout/SectionNav";
import { EmptyState, PageHeader, SectionCard } from "@/components/ui/primitives";
import {
  getDigestLibraryIndex,
  listResearchDigests,
} from "@/lib/services/research";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

const RELEVANCE_META: Record<string, { label: string; className: string }> = {
  high: {
    label: "High relevance",
    className: "bg-[var(--amber-soft)] text-[var(--amber)]",
  },
  medium: {
    label: "Worth a look",
    className: "bg-[var(--accent-soft)] text-[var(--accent-ink)]",
  },
  low: {
    label: "Screened",
    className: "bg-[var(--surface-2)] text-[var(--ink-3)]",
  },
};

/**
 * Every Rho review digest, newest first — the reading room for reports that
 * used to be reachable only through a CEO Brief row or a bibliography link.
 * Full text stays in the vault reader; this page is the index.
 */
export default async function ResearchDigestsPage() {
  const [digests, library] = await Promise.all([
    listResearchDigests(),
    getDigestLibraryIndex(),
  ]);

  return (
    <div>
      <ResearchNav />
      <PageHeader
        title="Review digests"
        subtitle="Every completed Rho review, newest first. The verdict is the one line worth reading; open a row for the full report."
      />
      <SectionCard title={`Digests · ${digests.length}`}>
        {digests.length ? (
          <ul className="divide-y">
            {digests.map((digest) => {
              const meta = RELEVANCE_META[digest.relevance];
              const filed = library[digest.relPath];
              return (
                <li key={digest.relPath} className="py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/vault/${digest.relPath}`}
                      className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--ink)] hover:text-[var(--accent-ink)] hover:underline"
                    >
                      {digest.title}
                    </Link>
                    {meta && (
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-2 py-px text-[10px] font-semibold uppercase tracking-[0.08em]",
                          meta.className,
                        )}
                      >
                        {meta.label}
                      </span>
                    )}
                    <span className="shrink-0 text-xs tabular-nums text-[var(--ink-3)]">
                      {digest.date}
                    </span>
                  </div>
                  {digest.verdict && (
                    <p className="mt-1 line-clamp-2 text-xs text-[var(--ink-2)]">
                      {digest.verdict}
                    </p>
                  )}
                  {filed && (
                    <p className="mt-1 text-[11px] text-[var(--ink-3)]">
                      Filed in library: {filed.targetLabel}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState
            title="No digests yet"
            description="Completed Rho reviews land here automatically — request one from the Newsletters tab."
          />
        )}
      </SectionCard>
    </div>
  );
}
