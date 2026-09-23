import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import { decoratePercents } from "@/components/ui/PercentDelta";
import { MermaidDiagram } from "@/components/vault/MermaidDiagram";

/**
 * Reader for one vault markdown file.
 *
 * Two things the old inline renderer got wrong:
 *
 * 1. YAML frontmatter was passed straight to ReactMarkdown. A `---` line
 *    following text is a setext heading, so the entire metadata block collapsed
 *    into one giant <h2> paragraph at the top of every agent-written document.
 *    Frontmatter is now parsed out and promoted to a real header.
 *
 * 2. Styling was `prose prose-sm prose-headings:*` - Tailwind Typography
 *    classes, but that plugin is not installed. They were inert, and preflight
 *    reset every heading to inherit, so `## Problem` computed to 16px/400,
 *    identical to body copy. Styling now comes from `.prose-doc` in globals.css.
 *
 * The header is built here rather than written into the markdown so the file
 * stays portable: Obsidian renders its own properties panel from the same
 * frontmatter, and no inline HTML has to survive two different parsers.
 */

const TYPE_LABELS: Record<string, string> = {
  "lit-review": "Literature review",
  "paper-digest": "Paper digest",
  draft: "Draft reply",
  "wiki-page": "Wiki page",
  meeting: "Meeting note",
  "lab-notebook": "Lab notebook",
};

const RELEVANCE_STYLES: Record<string, { bg: string; fg: string; label: string }> = {
  high: { bg: "var(--green-soft)", fg: "var(--green)", label: "High relevance" },
  medium: { bg: "var(--amber-soft)", fg: "var(--amber)", label: "Medium relevance" },
  low: { bg: "var(--gray-soft)", fg: "var(--ink-3)", label: "Low relevance" },
};

/** Flatten a rendered markdown node back to plain text for marker detection. */
function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) {
    return textOf((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}

const GAP_MARKER = "INSUFFICIENT INFORMATION";

// Documents where a signed percentage is a market move worth tinting. Scoped by
// type rather than applied everywhere: a "-15%" in a grant budget or a protocol
// note is a quantity, not a gain or a loss, and colouring it would assert a
// direction the document never claimed.
const MARKET_DOC_TYPES = new Set(["watchlist-brief", "markets-digest", "max-stock-research"]);

/** `node` is react-markdown's AST handle, not a DOM attribute - React warns on it. */
function domProps<T extends { node?: unknown }>({ ...props }: T): Omit<T, "node"> {
  delete props.node;
  return props;
}

function Chip({ bg, fg, children }: { bg: string; fg: string; children: ReactNode }) {
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-medium"
      style={{ background: bg, color: fg }}
    >
      {children}
    </span>
  );
}

export function VaultDocument({
  fm,
  body,
  fallbackTitle,
}: {
  fm: Record<string, string>;
  body: string;
  fallbackTitle: string;
}) {
  const title = fm.title || fallbackTitle;
  const typeLabel = fm.type ? (TYPE_LABELS[fm.type] ?? fm.type) : "";

  // The markdown carries `# Title` so the file reads correctly in Obsidian,
  // where the filename is a slug and frontmatter is a properties panel. Here
  // the header already renders the title, so drop the duplicate.
  const markdown = fm.title
    ? body.replace(/^\s*#\s+.*(\r?\n)+/, "")
    : body;
  const relevance = RELEVANCE_STYLES[(fm.relevance || "").toLowerCase()];
  const marketDoc = MARKET_DOC_TYPES.has((fm.type || "").toLowerCase());
  const tint = (children: ReactNode) => (marketDoc ? decoratePercents(children) : children);
  const link = fm.url || (fm.paper_id?.startsWith("10.") ? `https://doi.org/${fm.paper_id}` : "");

  // Eyebrow: provenance, in one muted line. Journal beats `source` when both
  // exist - "Nature Biotechnology" tells their more than "nature-biotechnology".
  const eyebrow = [typeLabel, fm.journal || fm.source, fm.created || fm.date]
    .map((v) => (v || "").trim())
    .filter(Boolean);

  const hasHeader = eyebrow.length > 0 || Boolean(fm.title) || Boolean(relevance);

  return (
    <div>
      {hasHeader && (
        <header className="mb-6 border-b border-[var(--border)] pb-5">
          {eyebrow.length > 0 && (
            <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--ink-3)]">
              {eyebrow.join("  ·  ")}
            </p>
          )}
          <h1 className="text-[1.35rem] font-[650] leading-[1.3] text-[var(--ink)]">
            {title}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {relevance && (
              <Chip bg={relevance.bg} fg={relevance.fg}>
                {relevance.label}
              </Chip>
            )}
            {fm.target_title && (
              <Chip bg="var(--accent-soft)" fg="var(--accent-ink)">
                {fm.target_type === "resource" ? "Resource" : "Project"} ·{" "}
                {fm.target_title}
              </Chip>
            )}
            {link && (
              <a
                href={link}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-[var(--ink-3)] hover:text-[var(--ink)]"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                {fm.paper_id?.startsWith("10.") ? fm.paper_id : "Source"}
              </a>
            )}
          </div>
        </header>
      )}

      {/* Field-label styling (the uppercase H3 eyebrow) applies only where an
          H3 is a fixed label. Elsewhere - the daily paper digest puts a paper
          title in each H3 - it would shrink real content into a label. */}
      <div className={fm.type === "lit-review" ? "prose-doc prose-doc-fields" : "prose-doc"}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // Everything react-markdown passes down (the task-list class on a
            // checkbox item, a table cell's alignment) has to survive, or these
            // overrides silently strip formatting from every document.
            li({ children, ...props }) {
              return <li {...domProps(props)}>{tint(children)}</li>;
            },
            // A ```mermaid fence is a diagram (notebook pipelines); every other
            // fence stays a code block.
            pre({ children, ...props }) {
              const code = Array.isArray(children) ? children[0] : children;
              const className =
                typeof code === "object" && code && "props" in code
                  ? String((code as { props?: { className?: string } }).props?.className ?? "")
                  : "";
              if (className.split(/\s+/).includes("language-mermaid")) {
                return <MermaidDiagram source={textOf(code).replace(/\n$/, "")} />;
              }
              return <pre {...domProps(props)}>{children}</pre>;
            },
            td({ children, ...props }) {
              return <td {...domProps(props)}>{tint(children)}</td>;
            },
            p({ children }) {
              const text = textOf(children).trim();
              if (!text.toUpperCase().startsWith(GAP_MARKER)) {
                return <p>{tint(children)}</p>;
              }
              // Keep the reviewer's explanation of *why* the source was thin;
              // drop the shouty marker, which the chip now carries.
              const reason = text
                .slice(GAP_MARKER.length)
                .replace(/^[\s—–:.-]+/, "")
                .trim();
              return (
                <p className="doc-gap">
                  <span className="doc-gap-chip">No data</span>
                  <span>{reason || "The source did not support an answer here."}</span>
                </p>
              );
            },
          }}
        >
          {markdown}
        </ReactMarkdown>
      </div>
    </div>
  );
}
