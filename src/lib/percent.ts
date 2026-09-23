/**
 * Signed-percentage detection, shared by every market surface.
 *
 * Only *explicitly signed* percentages are recognised. "+0.13%" and "-1.57%"
 * carry their direction in the text itself, so colouring them adds no claim the
 * source did not make. A bare "0.7%" does not: "the Kospi gained 0.7%" and
 * "fell 0.7%" are the same token, and inferring direction from the surrounding
 * sentence is exactly the kind of assertion the markets team is built to avoid.
 * The cost is that some real moves stay uncoloured; the alternative is a red
 * number on a day the stock rose.
 */

export type SignedPercent = {
  /** Fractional value: -0.0157 for "-1.57%". */
  value: number;
  /** Display token, normalised to an ASCII sign so it copies cleanly. */
  label: string;
  direction: "up" | "down" | "flat";
};

// The sign may be ASCII hyphen, unicode minus, or plus. En dash is deliberately
// excluded - it is a range separator ("2-3%" meaning two to three percent).
//
// Two rules keep ranges from reading as negatives, and both come from real
// briefs. The lookbehind rejects a preceding word character, "." or "%", so
// neither "1-2%" nor "the yield rose to 4.70%-4.72%" produces a red -4.72%.
// And no whitespace is allowed between the sign and the digits, so a spaced
// range ("roughly 2 - 3%") is not a move either. A genuine signed move is
// always written tight: "+0.13%", "-1.57%".
const SIGNED_PERCENT_SOURCE = "(?<![\\w.%])([+\\-\\u2212])(\\d{1,3}(?:,\\d{3})*(?:\\.\\d+)?)\\s?%";

/** A fresh regex per call - a shared global one would carry `lastIndex`. */
function signedPercentRegex(): RegExp {
  return new RegExp(SIGNED_PERCENT_SOURCE, "g");
}

function toSigned(sign: string, digits: string): SignedPercent {
  const magnitude = Number(digits.replace(/,/g, ""));
  const negative = sign !== "+";
  if (!Number.isFinite(magnitude) || magnitude === 0) {
    return { value: 0, label: `${digits}%`, direction: "flat" };
  }
  return {
    value: (negative ? -magnitude : magnitude) / 100,
    label: `${negative ? "-" : "+"}${digits}%`,
    direction: negative ? "down" : "up",
  };
}

/**
 * Split free prose into literal runs and the signed percentages between them,
 * so a renderer can tint the numbers without touching the sentence around them.
 */
export function splitSignedPercents(text: string): Array<string | SignedPercent> {
  const source = String(text ?? "");
  const regex = signedPercentRegex();
  const parts: Array<string | SignedPercent> = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(source)) !== null) {
    if (match.index > cursor) parts.push(source.slice(cursor, match.index));
    parts.push(toSigned(match[1], match[2]));
    cursor = match.index + match[0].length;
  }
  if (!parts.length) return [source];
  if (cursor < source.length) parts.push(source.slice(cursor));
  return parts;
}

export function firstSignedPercent(text: string): SignedPercent | null {
  const match = signedPercentRegex().exec(String(text ?? ""));
  return match ? toSigned(match[1], match[2]) : null;
}

// The watchlist brief writes its own uncertainty into the Move field: COIN and
// EWY both read "could not be verified" and then quote a *stale* percentage
// from a previous session. Lifting that number into the move column would
// present yesterday's quote as today's move, which is the one way this display
// could actively mislead.
const UNVERIFIED = /\b(?:could not|cannot|can't|was not|were not|not)\s+(?:be\s+)?verif/i;

export type MoveReading =
  /** The brief reported a move, and this is it. */
  | { status: "delta"; delta: SignedPercent }
  /** The brief explicitly declined to verify today's move. */
  | { status: "unverified" }
  /** No move was reported - a macro note rather than a quote. */
  | { status: "none" };

/** What a watchlist row should show for its move, and why. */
export function readMove(moveText: string | null | undefined): MoveReading {
  const source = String(moveText ?? "");
  const match = signedPercentRegex().exec(source);
  const doubt = UNVERIFIED.exec(source);
  if (!match) return doubt ? { status: "unverified" } : { status: "none" };
  if (doubt && doubt.index < match.index) return { status: "unverified" };
  return { status: "delta", delta: toSigned(match[1], match[2]) };
}

/** Build a delta from a computed fraction (0.0421 -> "+4.21%"). */
export function signedPercentFromFraction(
  value: number | null | undefined,
  digits = 2,
): SignedPercent | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const rounded = Number((value * 100).toFixed(digits));
  const magnitude = Math.abs(rounded).toFixed(digits);
  if (rounded === 0) return { value: 0, label: `${magnitude}%`, direction: "flat" };
  return {
    value,
    label: `${rounded > 0 ? "+" : "-"}${magnitude}%`,
    direction: rounded > 0 ? "up" : "down",
  };
}

/**
 * A signed dollar amount in the same shape, so `PercentDelta` draws it with
 * the same glyph and tint: "+$0.60", "-$12.30", "$0.00" flat. One component
 * per signed delta, whatever the unit.
 */
export function signedMoney(
  value: number | null | undefined,
): SignedPercent | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const rounded = Number(value.toFixed(2));
  const magnitude = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(Math.abs(rounded));
  if (rounded === 0) return { value: 0, label: magnitude, direction: "flat" };
  return {
    value,
    label: `${rounded > 0 ? "+" : "-"}${magnitude}`,
    direction: rounded > 0 ? "up" : "down",
  };
}
