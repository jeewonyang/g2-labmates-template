import { Fragment, cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { splitSignedPercents, type SignedPercent } from "@/lib/percent";
import { cn } from "@/lib/utils";

/**
 * The one way a +/- percentage is drawn anywhere in the app.
 *
 * Direction is carried by a glyph as well as by colour, so the reading does not
 * depend on distinguishing green from red - the numbers are small, and half of
 * these surfaces are read on a tablet in daylight.
 *
 * Two variants, one component: `value` for a standalone figure in its own cell
 * (a metric, a watchlist row), `inline` for a number sitting inside a sentence,
 * where a tinted chip is what makes it findable in a paragraph of prose.
 */

const TONES = {
  up: { fg: "var(--green)", bg: "var(--green-soft)", glyph: "▲" },
  down: { fg: "var(--red)", bg: "var(--red-soft)", glyph: "▼" },
  flat: { fg: "var(--ink-3)", bg: "var(--gray-soft)", glyph: "–" },
} as const;

export function PercentDelta({
  delta,
  variant = "value",
  className,
  title,
}: {
  delta: SignedPercent;
  variant?: "value" | "inline";
  className?: string;
  title?: string;
}) {
  const tone = TONES[delta.direction];
  const inline = variant === "inline";
  return (
    <span
      className={cn(
        "inline-flex items-baseline gap-0.5 font-mono font-semibold tabular-nums",
        inline && "mx-px rounded px-1 py-px text-[0.92em]",
        className,
      )}
      style={inline ? { background: tone.bg, color: tone.fg } : { color: tone.fg }}
      title={title}
    >
      <span aria-hidden="true" className="text-[0.78em]">
        {tone.glyph}
      </span>
      {delta.label}
    </span>
  );
}

// `code` keeps its literal text - a percentage inside a code span is a value
// being quoted, not a move being reported.
const OPAQUE = new Set(["code", "pre", "kbd"]);

/**
 * Tint every signed percentage inside already-rendered content.
 *
 * Recursion stops at custom components: react-markdown nests our own `p`
 * override inside our own `li` override, and each one decorates its own
 * children. Descending into the child element too would run the split twice
 * over the same text.
 */
export function decoratePercents(node: ReactNode): ReactNode {
  if (typeof node === "string") return renderParts(node);
  if (typeof node === "number") return node;
  if (Array.isArray(node)) {
    return node.map((child, index) => <Fragment key={index}>{decoratePercents(child)}</Fragment>);
  }
  if (!isValidElement(node)) return node;
  if (typeof node.type !== "string" || OPAQUE.has(node.type)) return node;
  const children = (node.props as { children?: ReactNode }).children;
  if (children == null) return node;
  return cloneElement(node as ReactElement<{ children?: ReactNode }>, undefined, decoratePercents(children));
}

function renderParts(text: string): ReactNode {
  const parts = splitSignedPercents(text);
  if (parts.length === 1 && typeof parts[0] === "string") return text;
  return parts.map((part, index) =>
    typeof part === "string" ? (
      <Fragment key={index}>{part}</Fragment>
    ) : (
      <PercentDelta key={index} delta={part} variant="inline" />
    ),
  );
}

/** Prose with its signed percentages tinted. */
export function PercentText({ children }: { children: ReactNode }) {
  return <>{decoratePercents(children)}</>;
}
