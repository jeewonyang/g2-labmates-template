/**
 * Live journal headline feeds for the Today research card.
 * Fetches public publisher RSS feeds server-side with a daily cache.
 * No dependency: a minimal RSS/Atom item parser is enough. Every failure
 * degrades to an { error: true } feed so Today never breaks.
 *
 * Only research articles are shown — news/editorial/preview items are
 * filtered out per publisher: Nature research DOIs start with s41586 (news
 * uses d41586), Science tags items with <dc:type>, Cell with <prism:section>.
 */

export type JournalItem = {
  title: string;
  link: string;
  summary: string | null;
  publishedAt: string | null;
  doi: string;
  authors: string | null;
  /** dc:type (Science) or prism:section (Cell) — used to filter to research. */
  section: string | null;
};

export type JournalFeed = {
  key: string;
  label: string;
  group: "core" | "specialty";
  homepage: string;
  items: JournalItem[];
  error: boolean;
};

/** Corrections/retractions are technically research-DOI items but not news-worthy. */
const NON_ARTICLE_TITLE = /^(publisher correction|author correction|correction|retraction|erratum|addendum)\b/i;
const DOI_IN_TEXT = /\b10\.\d{4,9}\/[-._;()/:a-z0-9]+\b/i;

type FeedConfig = {
  key: string;
  label: string;
  group: "core" | "specialty";
  homepage: string;
  url: string;
  isResearch: (item: JournalItem) => boolean;
  /** Drop summaries that are citation boilerplate rather than real text. */
  junkSummary?: RegExp;
};

const natureResearch = (doiPrefix: string) => (item: JournalItem) =>
  item.link.includes(`/articles/${doiPrefix}-`) && !NON_ARTICLE_TITLE.test(item.title);

const scienceResearch = (item: JournalItem) =>
  /research (article|resource)|^report$/i.test(item.section ?? "") &&
  !NON_ARTICLE_TITLE.test(item.title);

const cellResearch = (item: JournalItem) =>
  /(^|\s)(article|resource|report)s?$/i.test(item.section ?? "") &&
  !NON_ARTICLE_TITLE.test(item.title);

const FEEDS: FeedConfig[] = [
  {
    key: "nature",
    label: "Nature",
    group: "core",
    // The research-articles page/feed (nature.com/nature/research-articles[.rss])
    // is bot-challenged and returns an HTML wall, so we pull the current-issue
    // TOC feed and keep only research papers. Link out to research-articles.
    homepage: "https://www.nature.com/nature/research-articles",
    url: "https://www.nature.com/nature/journal/vaop/ncurrent/rss.rdf",
    // Research papers live under s41586- DOIs; news/comment under d41586-.
    isResearch: natureResearch("s41586"),
  },
  {
    key: "science",
    label: "Science",
    group: "core",
    // showFeed etoc IS the current-issue TOC (same as /toc/science/current).
    homepage: "https://www.science.org/toc/science/current",
    url: "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
    // dc:type: keep "Research Article"/"Research Resource"/"Report"; drop
    // Perspective, Editorial, In Depth, Feature, Letter, etc.
    isResearch: scienceResearch,
    // Science descriptions are just "Science, Volume 393, Page 28, July 2026."
    junkSummary: /^Science, Volume \d/i,
  },
  {
    key: "cell",
    label: "Cell",
    group: "core",
    // "New articles" = articles in press (inpress.rss), the freshest research.
    homepage: "https://www.cell.com/cell/newarticles",
    url: "https://www.cell.com/cell/inpress.rss",
    // Sections: Article, Short article, Resource vs Correction/Preview/Review/etc.
    isResearch: cellResearch,
  },
  {
    key: "nature-biotechnology",
    label: "Nat Biotech",
    group: "specialty",
    homepage: "https://www.nature.com/nbt/research-articles",
    url: "https://www.nature.com/nbt/current_issue/rss/",
    isResearch: natureResearch("s41587"),
  },
  {
    key: "nature-methods",
    label: "Nat Methods",
    group: "specialty",
    homepage: "https://www.nature.com/nmeth/research-articles",
    url: "https://www.nature.com/nmeth/journal/vaop/ncurrent/rss.rdf",
    isResearch: natureResearch("s41592"),
  },
  {
    key: "nature-biomedical-engineering",
    label: "Nat Biomed Eng",
    group: "specialty",
    homepage: "https://www.nature.com/natbiomedeng/research-articles",
    url: "https://www.nature.com/natbiomedeng/journal/vaop/ncurrent/rss.rdf",
    isResearch: natureResearch("s41551"),
  },
  {
    key: "science-translational-medicine",
    label: "Sci Transl Med",
    group: "specialty",
    homepage: "https://www.science.org/journal/stm",
    url: "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=stm",
    isResearch: scienceResearch,
    junkSummary: /^Science Translational Medicine, Volume \d/i,
  },
  {
    key: "cell-systems",
    label: "Cell Systems",
    group: "specialty",
    homepage: "https://www.cell.com/cell-systems/newarticles",
    url: "https://www.cell.com/cell-systems/inpress.rss",
    isResearch: cellResearch,
  },
];

function decodeEntities(s: string): string {
  return s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&amp;/g, "&");
}

function cleanText(raw: string | null, max = 200): string | null {
  if (!raw) return null;
  const text = decodeEntities(
    raw
      .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
      .replace(/<[^>]+>/g, " ")
  )
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return null;
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

function tag(block: string, name: string): string | null {
  const m = block.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)<\\/${name}>`, "i"));
  return m ? m[1] : null;
}

/**
 * Strip the "Nature Methods, Published online: 02 July 2026; doi:10.1038/…"
 * citation prefix Nature Portfolio feeds put in content:encoded.
 */
function stripCitationPrefix(text: string): string {
  return text.replace(/^[^,]+,\s*Published online: [^;]+;\s*doi:\S+\s*/i, "").trim();
}

/** Parse RSS 2.0 <item> or Atom <entry> blocks from a feed document. */
export function parseFeed(xml: string, limit = Infinity): JournalItem[] {
  const blocks = xml.match(/<(?:item|entry)[\s>][\s\S]*?<\/(?:item|entry)>/gi) ?? [];
  const items: JournalItem[] = [];
  for (const block of blocks) {
    const title = cleanText(tag(block, "title"), 300);
    if (!title) continue;

    // RSS: <link>url</link>; Atom: <link href="url"/>.
    let link = cleanText(tag(block, "link"), 2000) ?? "";
    if (!link) {
      const href = block.match(/<link[^>]*href=["']([^"']+)["']/i);
      link = href ? decodeEntities(href[1]) : "";
    }

    let summary = cleanText(
      tag(block, "description") ?? tag(block, "summary") ?? tag(block, "dc:description"),
      200
    );
    if (!summary) {
      // Nature has no description; content:encoded holds citation + teaser.
      const encoded = cleanText(tag(block, "content:encoded"), 400);
      const teaser = encoded ? stripCitationPrefix(encoded) : "";
      if (teaser && teaser !== title) {
        summary = teaser.length > 200 ? `${teaser.slice(0, 199).trimEnd()}…` : teaser;
      }
    }

    const section = cleanText(tag(block, "dc:type") ?? tag(block, "prism:section"), 60);
    const identifier =
      cleanText(tag(block, "prism:doi") ?? tag(block, "dc:identifier"), 500) ?? "";
    const doi = identifier.match(DOI_IN_TEXT)?.[0]?.toLowerCase() ?? "";
    const authors = cleanText(
      tag(block, "dc:creator") ?? tag(block, "author") ?? tag(block, "prism:author"),
      500,
    );
    const dateRaw =
      tag(block, "pubDate") ?? tag(block, "dc:date") ?? tag(block, "prism:publicationDate") ??
      tag(block, "published") ?? tag(block, "updated");
    const parsed = dateRaw ? new Date(dateRaw.trim()) : null;
    const publishedAt = parsed && !isNaN(parsed.getTime()) ? parsed.toISOString() : null;

    items.push({ title, link, summary, publishedAt, doi, authors, section });
    if (items.length >= limit) break;
  }
  return items;
}

async function fetchOne(feed: FeedConfig): Promise<JournalFeed> {
  try {
    const res = await fetch(feed.url, {
      headers: {
        // Some publishers block default fetch user agents.
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        Accept: "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
      },
      next: { revalidate: 24 * 60 * 60 },
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const xml = await res.text();
    const items = parseFeed(xml)
      .filter(feed.isResearch)
      .map((i) =>
        feed.junkSummary && i.summary && feed.junkSummary.test(i.summary)
          ? { ...i, summary: null }
          : i
      )
      .slice(0, 6);
    return {
      key: feed.key,
      label: feed.label,
      group: feed.group,
      homepage: feed.homepage,
      items,
      error: items.length === 0,
    };
  } catch {
    return {
      key: feed.key,
      label: feed.label,
      group: feed.group,
      homepage: feed.homepage,
      items: [],
      error: true,
    };
  }
}

type BiorxivRow = {
  doi?: string;
  title?: string;
  authors?: string;
  abstract?: string;
  date?: string;
  category?: string;
};

async function fetchBiorxivFeed(): Promise<JournalFeed> {
  const fallback: JournalFeed = {
    key: "biorxiv",
    label: "bioRxiv",
    group: "specialty",
    homepage: "https://www.biorxiv.org/",
    items: [],
    error: true,
  };
  try {
    const end = new Date();
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - 7);
    const interval = `${start.toISOString().slice(0, 10)}/${end
      .toISOString()
      .slice(0, 10)}`;
    const response = await fetch(
      `https://api.biorxiv.org/details/biorxiv/${interval}/0`,
      {
        headers: {
          "User-Agent": "SecondBrain/1.0 (personal research monitor)",
          Accept: "application/json",
        },
        next: { revalidate: 24 * 60 * 60 },
        signal: AbortSignal.timeout(12_000),
      },
    );
    if (!response.ok) return fallback;
    const payload = (await response.json()) as { collection?: BiorxivRow[] };
    const items = (payload.collection ?? [])
      .filter((row) => row.doi && row.title)
      .sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")))
      .slice(0, 8)
      .map(
        (row): JournalItem => ({
          title: String(row.title || "").replace(/\s+/g, " ").trim(),
          link: `https://doi.org/${row.doi}`,
          summary: cleanText(String(row.abstract || ""), 200),
          publishedAt: row.date
            ? new Date(`${row.date}T00:00:00Z`).toISOString()
            : null,
          doi: String(row.doi || "").toLowerCase(),
          authors: cleanText(String(row.authors || ""), 500),
          section: row.category || "preprint",
        }),
      );
    return { ...fallback, items, error: items.length === 0 };
  } catch {
    return fallback;
  }
}

export async function fetchJournalFeeds(): Promise<JournalFeed[]> {
  const [publishers, biorxiv] = await Promise.all([
    Promise.all(FEEDS.map(fetchOne)),
    fetchBiorxivFeed(),
  ]);
  return [...publishers, biorxiv];
}
