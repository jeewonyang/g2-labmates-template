import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { getWikiGraph } from "@/lib/services/wiki";
import { PageHeader } from "@/components/ui/primitives";
import { WikiGraph } from "@/components/wiki/WikiGraph";
import { KnowledgeNav } from "@/components/layout/SectionNav";

export const dynamic = "force-dynamic";

/** Interactive force-directed graph of the wiki's [[wikilink]] network.
 * Static segment, so it takes precedence over the /wiki/[[...slug]] catch-all. */
export default async function WikiGraphPage() {
  const data = await getWikiGraph();
  return (
    <div>
      <KnowledgeNav />
      <nav className="mb-3 flex flex-wrap items-center gap-1 text-xs text-[var(--ink-3)]">
        <Link href="/wiki" className="hover:text-[var(--accent-ink)]">Wiki</Link>
        <ChevronRight className="h-3 w-3" />
        <span className="text-[var(--ink-2)]">Graph</span>
      </nav>
      <PageHeader
        title="Wiki Graph"
        subtitle={`${data.nodes.length} pages, ${data.links.length} links. Drag to explore, scroll to zoom, click a node to open it.`}
      />
      <WikiGraph data={data} />
    </div>
  );
}
