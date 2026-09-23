"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { WikiGraphData } from "@/lib/services/wiki";

// 2D canvas force graph (no Three.js). Loaded client-only: it touches `window`.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

/** Our node fields plus the x/y the force engine assigns during simulation. */
type GraphNode = {
  id: string;
  name: string;
  type: string;
  val: number;
  x?: number;
  y?: number;
};

/** The loose node shape the library hands to accessor/render callbacks (its own
 * NodeObject isn't exported). We accept this, then cast to GraphNode. */
type LibNode = { x?: number; y?: number; [key: string]: unknown };
const asNode = (n: LibNode) => n as unknown as GraphNode;

// Colors per page type, drawn on canvas so they must be literal (not CSS vars).
const TYPE_COLOR: Record<string, string> = {
  overview: "#6d7ff5", // accent
  concept: "#22d3ee", // cyan
  project: "#f59e0b", // amber
  entity: "#22c55e", // green
  person: "#a855f7", // purple
  summary: "#60a5fa", // blue
  untyped: "#9da7b8",
};
const TYPE_ORDER = ["overview", "concept", "project", "entity", "person", "summary"];
const EDGE_COLOR = "rgba(157,167,184,0.22)";
const LABEL_COLOR = "#e8ecf4";

function radius(val: number): number {
  return Math.max(3, Math.sqrt(val) * 2.2);
}

export function WikiGraph({ data }: { data: WikiGraphData }) {
  const router = useRouter();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hover, setHover] = useState<string | null>(null);

  // Track container size so the canvas fills the card responsively.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () =>
      setSize({ width: el.clientWidth, height: el.clientHeight || 480 });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const paintNode = useCallback(
    (raw: LibNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const node = asNode(raw);
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const r = radius(node.val);
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = TYPE_COLOR[node.type] || TYPE_COLOR.untyped;
      ctx.fill();
      if (hover === node.id) {
        ctx.lineWidth = 1.5 / globalScale;
        ctx.strokeStyle = LABEL_COLOR;
        ctx.stroke();
      }
      // Label once zoomed in enough, or always for the hovered node.
      if (globalScale > 1.3 || hover === node.id) {
        const fontSize = Math.max(2.5, 11 / globalScale);
        ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
        ctx.fillStyle = LABEL_COLOR;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(node.name, x, y + r + 1);
      }
    },
    [hover]
  );

  if (!data.nodes.length) {
    return (
      <p className="text-sm text-[var(--ink-3)]">
        No pages to graph yet. Ingest sources with the /wiki skill.
      </p>
    );
  }

  return (
    <div>
      <div
        ref={wrapRef}
        style={{ height: "70vh", minHeight: 480 }}
        className="relative w-full overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)]"
      >
        {size.width > 0 && (
          <ForceGraph2D
            graphData={data}
            width={size.width}
            height={size.height}
            backgroundColor="rgba(0,0,0,0)"
            nodeRelSize={4}
            nodeVal={(n: LibNode) => asNode(n).val}
            nodeLabel={(n: LibNode) => `${asNode(n).name} (${asNode(n).type})`}
            nodeColor={(n: LibNode) => TYPE_COLOR[asNode(n).type] || TYPE_COLOR.untyped}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(raw: LibNode, color: string, ctx: CanvasRenderingContext2D) => {
              const node = asNode(raw);
              const x = node.x ?? 0;
              const y = node.y ?? 0;
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(x, y, radius(node.val) + 2, 0, 2 * Math.PI);
              ctx.fill();
            }}
            linkColor={() => EDGE_COLOR}
            linkWidth={1}
            onNodeHover={(n: LibNode | null) => setHover(n ? asNode(n).id : null)}
            onNodeClick={(n: LibNode) => router.push(`/wiki/${asNode(n).id}`)}
            cooldownTicks={120}
          />
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-3 text-xs text-[var(--ink-2)]">
        {TYPE_ORDER.filter((t) => data.nodes.some((n) => n.type === t)).map((t) => (
          <span key={t} className="inline-flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: TYPE_COLOR[t] }}
            />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}
