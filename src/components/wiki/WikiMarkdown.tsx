import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders wiki page markdown, expanding [[wikilinks]] into internal links.
 *
 * `[[target]]` / `[[target|label]]` become `[label](/wiki/<slug>)` via a regex
 * pass before ReactMarkdown, then an `a` renderer routes /wiki/* through
 * next/link for client navigation. A remark plugin could replace the regex
 * later; the tradeoff today is that [[...]] inside code fences also expands
 * (rare in this corpus).
 */

function slugify(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function expandWikilinks(md: string): string {
  return md.replace(/\[\[([^\]]+)\]\]/g, (_all, inner: string) => {
    const [target, label] = inner.split("|");
    const text = (label ?? target).trim();
    return `[${text}](/wiki/${slugify(target)})`;
  });
}

export function WikiMarkdown({ children }: { children: string }) {
  return (
    <div className="prose-sb">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children, ...rest }) {
            if (href && href.startsWith("/wiki/")) {
              return (
                <Link href={href} className="text-[var(--accent-ink)]">
                  {children}
                </Link>
              );
            }
            return (
              <a href={href} {...rest}>
                {children}
              </a>
            );
          },
        }}
      >
        {expandWikilinks(children)}
      </ReactMarkdown>
    </div>
  );
}
