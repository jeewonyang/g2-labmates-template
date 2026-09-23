import Link from "next/link";
import { Folder, FileText, ChevronRight } from "lucide-react";
import { listVault, readVaultFile, parseFrontmatter } from "@/lib/services/secondbrain";
import { PageHeader, Card, EmptyState } from "@/components/ui/primitives";
import { KnowledgeNav } from "@/components/layout/SectionNav";
import { VaultDocument } from "@/components/vault/VaultDocument";

export const dynamic = "force-dynamic";

/**
 * Read-only browser for VAULT/Memory/ (daily logs, meetings, research, drafts,
 * the memory files). Scoped to Memory/ - Finance/ and Personal/ are outside it
 * and unreachable (path traversal is blocked in the service).
 */
export default async function VaultPage({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path: segments = [] } = await params;
  const relPath = segments.map(decodeURIComponent).join("/");
  const isFile = relPath.endsWith(".md");

  const crumbs = segments.map(decodeURIComponent);

  if (isFile) {
    const content = await readVaultFile(relPath);
    const fileName = crumbs[crumbs.length - 1] ?? "File";
    // The document renders its own title from frontmatter, so no PageHeader
    // here - it would repeat the title as a raw filename directly above it.
    const { fm, body } = content ? parseFrontmatter(content) : { fm: {}, body: "" };
    return (
      <div>
        <KnowledgeNav />
        <Breadcrumbs crumbs={crumbs} />
        {content === null ? (
          <EmptyState title="Not found" description="This file isn't in the memory vault." />
        ) : (
          <Card className="max-w-[72ch] p-6 sm:p-8">
            <VaultDocument
              fm={fm}
              body={body}
              fallbackTitle={fileName.replace(/\.md$/, "")}
            />
          </Card>
        )}
      </div>
    );
  }

  const entries = await listVault(relPath);
  return (
    <div>
      <KnowledgeNav />
      <Breadcrumbs crumbs={crumbs} />
      <PageHeader
        title={crumbs.length ? crumbs[crumbs.length - 1] : "Memory vault"}
        subtitle={crumbs.length ? undefined : "Browse your Second Brain's memory — daily logs, meetings, research, drafts. Read-only."}
      />
      {!entries || entries.length === 0 ? (
        <EmptyState title="Empty" description="Nothing here yet." />
      ) : (
        <Card className="divide-y p-0">
          {entries.map((e) => (
            <Link
              key={e.relPath}
              href={`/vault/${e.relPath.split("/").map(encodeURIComponent).join("/")}`}
              className="flex items-center gap-2.5 px-4 py-2.5 text-sm transition-colors hover:bg-[var(--surface-hover)]"
            >
              {e.isDir ? (
                <Folder className="h-4 w-4 shrink-0 text-[var(--accent)]" />
              ) : (
                <FileText className="h-4 w-4 shrink-0 text-[var(--ink-3)]" />
              )}
              <span className="flex-1 text-[var(--ink)]">{e.name}</span>
              {e.isDir && <ChevronRight className="h-4 w-4 text-[var(--ink-3)]" />}
            </Link>
          ))}
        </Card>
      )}
    </div>
  );
}

function Breadcrumbs({ crumbs }: { crumbs: string[] }) {
  return (
    <nav className="mb-3 flex flex-wrap items-center gap-1 text-xs text-[var(--ink-3)]">
      <Link href="/vault" className="hover:text-[var(--accent-ink)]">Vault</Link>
      {crumbs.map((c, i) => {
        const href = `/vault/${crumbs.slice(0, i + 1).map(encodeURIComponent).join("/")}`;
        return (
          <span key={href} className="flex items-center gap-1">
            <ChevronRight className="h-3 w-3" />
            <Link href={href} className="hover:text-[var(--accent-ink)]">{c}</Link>
          </span>
        );
      })}
    </nav>
  );
}
