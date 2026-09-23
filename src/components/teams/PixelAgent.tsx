/**
 * Pixel-art agent sprites for the office floor.
 *
 * Drawn as inline SVG rects from a character map rather than shipped as image
 * assets: the sprite stays themeable (every colour is a token or a per-team
 * palette), scales crisply at any size via `shape-rendering: crispEdges`, and
 * a future team is one palette entry rather than a new PNG.
 *
 * The pose is DERIVED FROM REAL LEDGER STATE, never decorative. A waving agent
 * means jobs are genuinely waiting on them; a sleeping one means the queue is
 * actually empty. If the animation and the numbers ever disagree, the animation
 * is the bug — this is a status display wearing a costume, not a cartoon.
 */

export type AgentState = "idle" | "ready" | "working" | "needs" | "alert";

export interface Palette {
  hair: string;
  skin: string;
  body: string;
  accent: string;
  eye: string;
}

/**
 * One palette per team. Colours come from the app's token set so the office
 * reads as part of the dashboard rather than a pasted-in game screenshot.
 */
export const TEAM_PALETTES: Record<string, Palette> = {
  research: {
    hair: "#3b2f2a",
    skin: "#f0c9a4",
    body: "#e8ecf4", // lab coat
    accent: "#22d3ee",
    eye: "#1a1f2b",
  },
  admin: {
    hair: "#2b2118",
    skin: "#e8b48c",
    body: "#60a5fa",
    accent: "#fbbf24", // headset
    eye: "#1a1f2b",
  },
  security: {
    hair: "#1f1a17",
    skin: "#c98d63",
    body: "#7c8598",
    accent: "#f87171", // badge
    eye: "#1a1f2b",
  },
  vault: {
    hair: "#5a3a22",
    skin: "#f0c9a4",
    body: "#c084fc",
    accent: "#fbbf24",
    eye: "#1a1f2b",
  },
  // Research team at one table (2026-09-21): Rho plus LabSerf's agents
  // (Luma = labserf, Clio = cloner, Sage = advisor; keyed by member id).
  "research-rho": {
    hair: "#3b2f2a",
    skin: "#f0c9a4",
    body: "#e8ecf4", // lab coat, as before
    accent: "#22d3ee",
    eye: "#1a1f2b",
  },
  "research-labserf": {
    hair: "#1f1a17",
    skin: "#d9a679",
    body: "#a5b4fc", // periwinkle scrubs - the data bench
    accent: "#22d3ee", // cytometer laser
    eye: "#1a1f2b",
  },
  "research-cloner": {
    hair: "#5a3a22",
    skin: "#e8b48c",
    body: "#86efac", // bench green
    accent: "#f472b6", // plasmid map
    eye: "#1a1f2b",
  },
  "research-advisor": {
    hair: "#d1d5db", // the senior scientist
    skin: "#f0c9a4",
    body: "#92400e", // tweed
    accent: "#fde68a",
    eye: "#1a1f2b",
  },
  // Argus (2026-09-22): LabSerf's bench agents as one desk.
  "research-argus": {
    hair: "#1f1a17",
    skin: "#d9a679",
    body: "#a5b4fc", // periwinkle scrubs - the bench
    accent: "#22d3ee", // cytometer laser
    eye: "#1a1f2b",
  },
  // The Quick Capture coding agent. Not a ledger team - it has no producer,
  // no cadence, and no review gate - but it works the same floor, so it gets
  // a desk and a palette like everyone else.
  coding: {
    hair: "#2f2a3d",
    skin: "#d9a679",
    body: "#38bdf8",
    accent: "#a3e635", // terminal green
    eye: "#1a1f2b",
  },
};

export const FALLBACK_PALETTE: Palette = {
  hair: "#3b2f2a",
  skin: "#e8b48c",
  body: "#9da7b8",
  accent: "#6d7ff5",
  eye: "#1a1f2b",
};

/**
 * 16x16 chibi: oversized head, two-pixel eyes, torso cut off at desk height.
 * Legend: h hair, s skin, e eye, m mouth, b body, a accent, '.' transparent.
 * Arms are drawn separately so they can animate independently of the body.
 */
const SPRITE: string[] = [
  "................",
  "....hhhhhhhh....",
  "...hhhhhhhhhh...",
  "..hhhssssssshh..",
  "..hhsssssssssh..",
  "..hseessseessh..",
  "..hssssssssssh..",
  "..hssssmmssssh..",
  "...ssssssssss...",
  "....ssssssss....",
  "......bbbb......",
  "...bbbbbbbbbb...",
  "..bbbbbbbbbbbb..",
  "..bbbbaaaabbbb..",
  "..bbbbbbbbbbbb..",
  "................",
];

/** Rows 5 (eyes) are re-drawn on top so they can blink independently. */
const EYE_PIXELS: Array<[number, number]> = [
  [4, 5],
  [5, 5],
  [9, 5],
  [10, 5],
];

function colorFor(ch: string, p: Palette): string | null {
  switch (ch) {
    case "h":
      return p.hair;
    case "s":
      return p.skin;
    case "b":
      return p.body;
    case "a":
      return p.accent;
    case "e":
      return p.eye;
    case "m":
      return "#a8624f";
    default:
      return null;
  }
}

/**
 * The drawing box, deliberately larger than the 16x16 sprite.
 *
 * The zzz and the speech bubble sit at x 12..17, and the arms swing out past
 * the body when waving. Earlier these relied on `overflow: visible` to escape a
 * 16x16 viewBox - which worked until the sprite landed inside a card with
 * `overflow: hidden` for its rounded corners, and got sliced off. Giving the
 * viewBox real margin keeps every pixel inside the element's own box, so no
 * ancestor can clip it.
 */
const VB = { x: -1, y: -2, w: 20, h: 19 };

/** Per-state arm animation class. Kept in globals.css beside the keyframes. */
const ARM_CLASS: Record<AgentState, { left: string; right: string }> = {
  idle: { left: "", right: "" },
  ready: { left: "", right: "" },
  working: { left: "agent-type-a", right: "agent-type-b" },
  needs: { left: "", right: "agent-wave" },
  alert: { left: "agent-panic", right: "agent-panic" },
};

const BODY_CLASS: Record<AgentState, string> = {
  idle: "agent-sleep",
  ready: "agent-bob",
  working: "agent-bob-fast",
  needs: "agent-bob",
  alert: "agent-shake",
};

export function PixelAgent({
  team,
  state,
  size = 96,
  title,
}: {
  team: string;
  state: AgentState;
  size?: number;
  title?: string;
}) {
  const p = TEAM_PALETTES[team] ?? FALLBACK_PALETTE;
  const arms = ARM_CLASS[state];

  return (
    <svg
      width={Math.round((size * VB.w) / VB.h)}
      height={size}
      viewBox={`${VB.x} ${VB.y} ${VB.w} ${VB.h}`}
      shapeRendering="crispEdges"
      role="img"
      aria-label={title ?? `${team} agent, ${state}`}
    >
      {title ? <title>{title}</title> : null}

      <g className={BODY_CLASS[state]} style={{ transformOrigin: "8px 15px" }}>
        {/* Body + head from the sprite map. */}
        {SPRITE.map((row, y) =>
          row.split("").map((ch, x) => {
            const fill = colorFor(ch, p);
            if (!fill || ch === "e") return null;
            return (
              <rect
                key={`${x}-${y}`}
                x={x}
                y={y}
                width={1}
                height={1}
                fill={fill}
              />
            );
          })
        )}

        {/* Eyes drawn last so the blink can squash just these. */}
        <g className="agent-blink" style={{ transformOrigin: "8px 5.5px" }}>
          {EYE_PIXELS.map(([x, y]) => (
            <rect
              key={`eye-${x}`}
              x={x}
              y={y}
              width={1}
              height={1}
              fill={p.eye}
            />
          ))}
        </g>

        {/* Arms: separate groups, hinged at the shoulder. */}
        <g
          className={arms.left}
          style={{ transformOrigin: "3px 11px" }}
        >
          <rect x={1} y={11} width={2} height={4} fill={p.body} />
          <rect x={1} y={14} width={2} height={1} fill={p.skin} />
        </g>
        <g
          className={arms.right}
          style={{ transformOrigin: "13px 11px" }}
        >
          <rect x={13} y={11} width={2} height={4} fill={p.body} />
          <rect x={13} y={14} width={2} height={1} fill={p.skin} />
        </g>
      </g>

      {/* Status flourishes. */}
      {state === "idle" && (
        <g className="agent-zzz" fill="var(--ink-3)">
          <rect x={13} y={2} width={3} height={1} />
          <rect x={15} y={3} width={1} height={1} />
          <rect x={13} y={4} width={3} height={1} />
        </g>
      )}
      {state === "needs" && (
        <g className="agent-bubble">
          <rect x={12} y={0} width={5} height={5} fill="var(--amber)" rx={0.5} />
          <rect x={14} y={1} width={1} height={2} fill="#1a1f2b" />
          <rect x={14} y={3.5} width={1} height={1} fill="#1a1f2b" />
        </g>
      )}
      {state === "alert" && (
        <g className="agent-bubble">
          <rect x={12} y={0} width={5} height={5} fill="var(--red)" rx={0.5} />
          <rect x={14} y={1} width={1} height={2} fill="#1a1f2b" />
          <rect x={14} y={3.5} width={1} height={1} fill="#1a1f2b" />
        </g>
      )}
    </svg>
  );
}

/** A pixel desk + monitor for the agent to sit behind. */
export function PixelDesk({
  size = 96,
  screen = "var(--accent)",
  lit = true,
}: {
  size?: number;
  screen?: string;
  lit?: boolean;
}) {
  return (
    <svg
      width={size}
      height={size / 2}
      viewBox="0 0 16 8"
      shapeRendering="crispEdges"
      aria-hidden="true"
    >
      {/* Monitor */}
      <rect x={9} y={0} width={6} height={5} fill="#1d2330" />
      <rect
        x={10}
        y={1}
        width={4}
        height={3}
        fill={lit ? screen : "#11151d"}
        className={lit ? "agent-screen" : undefined}
      />
      <rect x={11} y={5} width={2} height={1} fill="#2b3344" />
      {/* Desk top */}
      <rect x={0} y={6} width={16} height={2} fill="#2b3344" />
      <rect x={0} y={6} width={16} height={1} fill="#3a4560" />
    </svg>
  );
}

/**
 * A large square meeting table for a team of three or more (2026-09-21).
 * One laptop per seat, facing its agent, lit in that agent's state colour -
 * so the table itself reads the room, the way each desk's monitor does.
 * `seats` lists each seat's side and screen colour (null = dark).
 */
export function PixelTable({
  size = 120,
  seats,
}: {
  size?: number;
  seats: Array<{ side: "top" | "right" | "bottom" | "left"; offset: number; screen: string | null }>;
}) {
  // 24x24 units: a rim, a surface, and laptops set in from each edge.
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      shapeRendering="crispEdges"
      aria-hidden="true"
    >
      <rect x={0} y={0} width={24} height={24} fill="#3a4560" />
      <rect x={1} y={1} width={22} height={22} fill="#2b3344" />
      <rect x={1} y={1} width={22} height={1} fill="#46526f" />
      {seats.map((seat, i) => {
        // offset is 0..1 along the side; laptops are 4x3 (or 3x4 on the sides).
        const along = Math.round(3 + seat.offset * 14);
        const screen = seat.screen ?? "#11151d";
        const lit = seat.screen !== null;
        const cls = lit ? "agent-screen" : undefined;
        if (seat.side === "top" || seat.side === "bottom") {
          const y = seat.side === "top" ? 2 : 19;
          return (
            <g key={i}>
              <rect x={along} y={y} width={4} height={3} fill="#1d2330" />
              <rect x={along + 1} y={seat.side === "top" ? y + 1 : y} width={2} height={2} fill={screen} className={cls} />
            </g>
          );
        }
        const x = seat.side === "left" ? 2 : 19;
        return (
          <g key={i}>
            <rect x={x} y={along} width={3} height={4} fill="#1d2330" />
            <rect x={seat.side === "left" ? x + 1 : x} y={along + 1} width={2} height={2} fill={screen} className={cls} />
          </g>
        );
      })}
    </svg>
  );
}
