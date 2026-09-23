import { promises as fs } from "fs";
import path from "path";
import { parseFrontmatter } from "./secondbrain";

/**
 * LLM Wiki bridge: reads the agent-maintained wiki at VAULT/Memory/wiki/ so the
 * dashboard can render pages, the catalog, and stats. Read-only, framework-free.
 *
 * Security: only reads under VAULT/Memory/wiki/. Slugs are validated against
 * SLUG_RE before any filesystem access, so path traversal is impossible.
 */

const REPO = process.cwd();
const WIKI = path.join(REPO, "VAULT", "Memory", "wiki");
const PAGES = path.join(WIKI, "pages");
const STATE = path.join(REPO, ".claude", "data", "state", "wiki-state.json");

const SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;
const RESERVED: Record<string, string> = {
  wiki: "WIKI.md",
  catalog: "catalog.md",
  log: "log.md",
};

export interface WikiPageMeta {
  slug: string;
  title: string;
  type: string;
  updated: string;
  sources: string[];
}

export interface WikiPage {
  meta: WikiPageMeta;
  body: string;
}

export interface WikiStats {
  pages: number;
  byType: Record<string, number>;
  sourcesIngested: number | null;
  sourcesPending: number | null;
  lastRun: string | null;
  lastLint: string | null;
  initialized: boolean;
}

/** Resolve a slug to an absolute path inside the wiki, or null if invalid. */
function resolveWikiPage(slug: string): string | null {
  if (slug in RESERVED) return path.join(WIKI, RESERVED[slug]);
  if (!SLUG_RE.test(slug)) return null;
  return path.join(PAGES, `${slug}.md`);
}

function metaFromFrontmatter(slug: string, fm: Record<string, string>): WikiPageMeta {
  return {
    slug,
    title: fm.title || slug,
    type: fm.type || "untyped",
    updated: fm.updated || "",
    sources: (fm.sources || "")
      .split(";")
      .map((s) => s.trim())
      .filter(Boolean),
  };
}

async function readPageFiles(): Promise<{ slug: string; fm: Record<string, string>; body: string }[]> {
  let names: string[];
  try {
    names = await fs.readdir(PAGES);
  } catch {
    return [];
  }
  const out = [];
  for (const name of names) {
    if (!name.endsWith(".md") || name === "index.md") continue;
    const slug = name.slice(0, -3);
    try {
      const raw = await fs.readFile(path.join(PAGES, name), "utf-8");
      const { fm, body } = parseFrontmatter(raw);
      out.push({ slug, fm, body });
    } catch {
      /* skip unreadable */
    }
  }
  return out;
}

/** All real pages grouped by frontmatter `type` (skips index.md and type: meta). */
export async function listWikiPages(): Promise<Record<string, WikiPageMeta[]>> {
  const groups: Record<string, WikiPageMeta[]> = {};
  for (const { slug, fm } of await readPageFiles()) {
    if (fm.type === "meta") continue;
    const meta = metaFromFrontmatter(slug, fm);
    (groups[meta.type] ||= []).push(meta);
  }
  for (const list of Object.values(groups)) {
    list.sort((a, b) => a.title.localeCompare(b.title));
  }
  return groups;
}

export async function readWikiPage(slug: string): Promise<WikiPage | null> {
  const abs = resolveWikiPage(slug);
  if (!abs) return null;
  try {
    const raw = await fs.readFile(abs, "utf-8");
    const { fm, body } = parseFrontmatter(raw);
    return { meta: metaFromFrontmatter(slug, fm), body };
  } catch {
    return null;
  }
}

/** Pages that link to `slug` via [[slug]] or [[slug|label]]. Full scan (small corpus). */
export async function getBacklinks(slug: string): Promise<WikiPageMeta[]> {
  if (!SLUG_RE.test(slug)) return [];
  const linkRe = /\[\[([^\]]+)\]\]/g;
  const out: WikiPageMeta[] = [];
  for (const { slug: s, fm, body } of await readPageFiles()) {
    if (s === slug || fm.type === "meta") continue;
    let m: RegExpExecArray | null;
    let found = false;
    while ((m = linkRe.exec(body)) !== null) {
      const target = slugify(m[1].split("|", 1)[0]);
      if (target === slug) {
        found = true;
        break;
      }
    }
    if (found) out.push(metaFromFrontmatter(s, fm));
  }
  return out.sort((a, b) => a.title.localeCompare(b.title));
}

export interface WikiGraphData {
  nodes: { id: string; name: string; type: string; val: number }[];
  links: { source: string; target: string }[];
}

/** Node/edge graph of the wiki: one node per page, one edge per [[wikilink]]
 * that resolves to another real page. Node `val` scales with degree so hubs
 * render larger. Uses the same link parsing as getBacklinks. */
export async function getWikiGraph(): Promise<WikiGraphData> {
  const pages = (await readPageFiles()).filter((p) => p.fm.type !== "meta");
  const slugSet = new Set(pages.map((p) => p.slug));
  const degree: Record<string, number> = {};
  const links: { source: string; target: string }[] = [];
  const seen = new Set<string>();
  for (const { slug, body } of pages) {
    for (const m of body.matchAll(/\[\[([^\]]+)\]\]/g)) {
      const target = slugify(m[1].split("|", 1)[0]);
      if (target === slug || !slugSet.has(target)) continue;
      const key = `${slug}->${target}`;
      if (seen.has(key)) continue;
      seen.add(key);
      links.push({ source: slug, target });
      degree[slug] = (degree[slug] || 0) + 1;
      degree[target] = (degree[target] || 0) + 1;
    }
  }
  const nodes = pages.map((p) => ({
    id: p.slug,
    name: p.fm.title || p.slug,
    type: p.fm.type || "untyped",
    val: 1 + (degree[p.slug] || 0),
  }));
  return { nodes, links };
}

export async function getWikiStats(): Promise<WikiStats> {
  const pages = await readPageFiles();
  const byType: Record<string, number> = {};
  let count = 0;
  for (const { fm } of pages) {
    if (fm.type === "meta") continue;
    byType[fm.type || "untyped"] = (byType[fm.type || "untyped"] || 0) + 1;
    count++;
  }
  let state: Record<string, unknown> = {};
  try {
    state = JSON.parse(await fs.readFile(STATE, "utf-8"));
  } catch {
    /* no state yet */
  }
  const sources = (state.sources as Record<string, unknown>) || null;
  return {
    pages: count,
    byType,
    sourcesIngested: sources ? Object.keys(sources).length : null,
    sourcesPending: null, // computed by the Python toolkit (needs a vault walk); not surfaced here
    lastRun: (state.last_run as string) || null,
    lastLint: (state.last_lint as string) || null,
    initialized: pages.length > 0 || (await exists(path.join(WIKI, "WIKI.md"))),
  };
}

async function exists(p: string): Promise<boolean> {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

/** Mirror of the Python slugify: lowercase, non-alphanumeric -> hyphen, trim. */
export function slugify(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
