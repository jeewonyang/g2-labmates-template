"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import type { WikiPageMeta } from "@/lib/services/wiki";
import { Card } from "@/components/ui/primitives";

const TYPE_ORDER = ["overview", "concept", "project", "entity", "person", "summary"];
const TYPE_LABEL: Record<string, string> = {
  overview: "Overviews",
  concept: "Concepts",
  project: "Projects",
  entity: "Entities",
  person: "People",
  summary: "Summaries",
};

/** Client-side title/type filter over the page list. Deep search stays with
 * the Python hybrid search (memory_search) via the chat/skill. */
export function WikiBrowser({ groups }: { groups: Record<string, WikiPageMeta[]> }) {
  const [q, setQ] = useState("");

  const types = useMemo(() => {
    const known = TYPE_ORDER.filter((t) => groups[t]?.length);
    const extra = Object.keys(groups).filter((t) => !TYPE_ORDER.includes(t));
    return [...known, ...extra.sort()];
  }, [groups]);

  const query = q.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!query) return groups;
    const out: Record<string, WikiPageMeta[]> = {};
    for (const [type, pages] of Object.entries(groups)) {
      const hits = pages.filter(
        (p) => p.title.toLowerCase().includes(query) || p.slug.includes(query)
      );
      if (hits.length) out[type] = hits;
    }
    return out;
  }, [groups, query]);

  const total = Object.values(filtered).reduce((n, l) => n + l.length, 0);

  return (
    <div className="space-y-5">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--ink-3)]" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter pages by title…"
          className="w-full rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--surface)] py-2 pl-9 pr-3 text-sm text-[var(--ink)] outline-none placeholder:text-[var(--ink-3)] focus:border-[var(--border-strong)]"
        />
      </div>

      {total === 0 ? (
        <p className="text-sm text-[var(--ink-3)]">No pages match “{q}”.</p>
      ) : (
        types
          .filter((t) => filtered[t]?.length)
          .map((type) => (
            <section key={type}>
              <h2 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--ink-3)]">
                {TYPE_LABEL[type] ?? type}
                <span className="text-[var(--ink-3)]">({filtered[type].length})</span>
              </h2>
              <Card className="divide-y p-0">
                {filtered[type].map((p) => (
                  <Link
                    key={p.slug}
                    href={`/wiki/${p.slug}`}
                    className="flex items-center gap-3 px-4 py-2.5 text-sm transition-colors hover:bg-[var(--surface-hover)]"
                  >
                    <span className="flex-1 text-[var(--ink)]">{p.title}</span>
                    {p.updated && (
                      <span className="text-xs text-[var(--ink-3)]">{p.updated}</span>
                    )}
                  </Link>
                ))}
              </Card>
            </section>
          ))
      )}
    </div>
  );
}

export { TYPE_LABEL };
