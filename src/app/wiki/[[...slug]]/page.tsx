import Link from "next/link";
import { ChevronRight, BookOpen, ScrollText, FileText, Link2 } from "lucide-react";
import {
  listWikiPages,
  readWikiPage,
  getBacklinks,
  getWikiStats,
} from "@/lib/services/wiki";
import { PageHeader, Card, EmptyState, Stat } from "@/components/ui/primitives";
import { Badge } from "@/components/ui/Badge";
import { WikiMarkdown } from "@/components/wiki/WikiMarkdown";
import { WikiBrowser } from "@/components/wiki/WikiBrowser";
import { KnowledgeNav } from "@/components/layout/SectionNav";

export const dynamic = "force-dynamic";

/**
 * The LLM Wiki (Karpathy pattern): an agent-maintained, cross-linked knowledge
 * layer over the vault, at VAULT/Memory/wiki/. Read-only view; pages are
 * written by Claude Code sessions via the `wiki` skill.
 */
export default async function WikiPage({
  params,
}: {
  params: Promise<{ slug?: string[] }>;
}) {
  const { slug: segments = [] } = await params;

  if (segments.length === 0) return <WikiIndex />;
  return <WikiPageView slug={decodeURIComponent(segments[0])} />;
}

async function WikiIndex() {
  const [groups, stats] = await Promise.all([listWikiPages(), getWikiStats()]);

  if (!stats.initialized) {
    return (
      <div>
        <KnowledgeNav />
        <PageHeader title="Wiki" />
        <EmptyState
          icon={<BookOpen className="h-6 w-6" />}
          title="Wiki not set up yet"
          description="Run `python .claude/scripts/wiki_build.py init`, then ingest sources with the /wiki skill."
        />
      </div>
    );
  }

  return (
    <div>
      <KnowledgeNav />
      <PageHeader
        title="Wiki"
        subtitle="An agent-curated, cross-linked knowledge layer over your vault. Read-only here — pages are written via the /wiki skill."
        actions={
          <div className="flex gap-2 text-sm">
            <Link href="/wiki/graph" className="text-[var(--accent-ink)] hover:underline">Graph</Link>
            <Link href="/wiki/catalog" className="text-[var(--accent-ink)] hover:underline">Catalog</Link>
            <Link href="/wiki/log" className="text-[var(--accent-ink)] hover:underline">Log</Link>
            <Link href="/wiki/wiki" className="text-[var(--accent-ink)] hover:underline">Schema</Link>
          </div>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Pages" value={stats.pages} />
        <Stat label="Sources ingested" value={stats.sourcesIngested ?? "—"} />
        <Stat label="Last built" value={stats.lastRun ? stats.lastRun.split(" ")[0] : "—"} hint={stats.lastRun?.split(" ")[1]} />
        <Stat label="Last lint" value={stats.lastLint ? stats.lastLint.split(" ")[0] : "—"} hint={stats.lastLint?.split(" ")[1]} />
      </div>

      {stats.pages === 0 ? (
        <EmptyState
          icon={<BookOpen className="h-6 w-6" />}
          title="No pages yet"
          description="The wiki is initialized but empty. Ingest sources with the /wiki skill to build it."
        />
      ) : (
        <WikiBrowser groups={groups} />
      )}
    </div>
  );
}

async function WikiPageView({ slug }: { slug: string }) {
  const [page, backlinks] = await Promise.all([readWikiPage(slug), getBacklinks(slug)]);

  if (!page) {
    return (
      <div>
        <KnowledgeNav />
        <WikiCrumbs title={slug} />
        <PageHeader title={slug} />
        <EmptyState
          icon={<FileText className="h-6 w-6" />}
          title="Not written yet"
          description="No wiki page exists for this link. It can be created by the /wiki skill."
        />
        {backlinks.length > 0 && <Backlinks pages={backlinks} />}
      </div>
    );
  }

  const isMeta = page.meta.type === "meta";

  return (
    <div>
      <KnowledgeNav />
      <WikiCrumbs title={page.meta.title} />
      <PageHeader
        title={page.meta.title}
        actions={
          <div className="flex items-center gap-2">
            {!isMeta && <Badge tone="accent">{page.meta.type}</Badge>}
            {page.meta.updated && (
              <span className="text-xs text-[var(--ink-3)]">updated {page.meta.updated}</span>
            )}
          </div>
        }
      />

      <Card className="p-6">
        <WikiMarkdown>{page.body}</WikiMarkdown>
      </Card>

      {page.meta.sources.length > 0 && <Sources paths={page.meta.sources} />}
      {backlinks.length > 0 && <Backlinks pages={backlinks} />}
    </div>
  );
}

function WikiCrumbs({ title }: { title: string }) {
  return (
    <nav className="mb-3 flex flex-wrap items-center gap-1 text-xs text-[var(--ink-3)]">
      <Link href="/wiki" className="hover:text-[var(--accent-ink)]">Wiki</Link>
      <ChevronRight className="h-3 w-3" />
      <span className="text-[var(--ink-2)]">{title}</span>
    </nav>
  );
}

function Sources({ paths }: { paths: string[] }) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--ink-3)]">
        <ScrollText className="h-3.5 w-3.5" /> Sources
      </h2>
      <Card className="divide-y p-0 text-sm">
        {paths.map((p) =>
          p.startsWith("Memory/") ? (
            <Link
              key={p}
              href={`/vault/${p.slice("Memory/".length).split("/").map(encodeURIComponent).join("/")}`}
              className="block px-4 py-2 font-mono text-xs text-[var(--accent-ink)] transition-colors hover:bg-[var(--surface-hover)]"
            >
              {p}
            </Link>
          ) : (
            <div key={p} className="px-4 py-2 font-mono text-xs text-[var(--ink-2)]">
              {p}
            </div>
          )
        )}
      </Card>
    </section>
  );
}

function Backlinks({ pages }: { pages: { slug: string; title: string }[] }) {
  return (
    <section className="mt-6">
      <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--ink-3)]">
        <Link2 className="h-3.5 w-3.5" /> Linked from
      </h2>
      <Card className="divide-y p-0 text-sm">
        {pages.map((p) => (
          <Link
            key={p.slug}
            href={`/wiki/${p.slug}`}
            className="block px-4 py-2 text-[var(--ink)] transition-colors hover:bg-[var(--surface-hover)]"
          >
            {p.title}
          </Link>
        ))}
      </Card>
    </section>
  );
}
