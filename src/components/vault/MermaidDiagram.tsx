"use client";

import { useEffect, useId, useState } from "react";

/**
 * A ```mermaid block drawn as a diagram (computational notebook entries,
 * 2026-09-22: the pipeline sits in Materials & Methods). Obsidian renders the
 * same fence natively, so the markdown file stays the one source.
 *
 * Mermaid is ~1 MB, so it loads on the first diagram, never with the page
 * bundle. `securityLevel: "strict"` sanitizes labels and disables click
 * handlers. Until it draws, and if the source does not parse, the block shows
 * as the code it is - a typo costs the picture, not the entry.
 */
export function MermaidDiagram({ source }: { source: string }) {
  const id = `mermaid-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          // A pipeline sketch, not a data dump: past this it shows as source.
          maxTextSize: 20_000,
          theme: "dark",
          // Mermaid computes shades from real colours, not CSS variables, so
          // these mirror the dark-only :root tokens in globals.css.
          themeVariables: {
            darkMode: true,
            background: "#0d1017",
            primaryColor: "#11151d",
            primaryBorderColor: "#2b3344",
            primaryTextColor: "#e8ecf4",
            secondaryColor: "#171c27",
            tertiaryColor: "#0d1017",
            lineColor: "#9da7b8",
            // The default edge-label box is light grey under light text.
            edgeLabelBackground: "#171c27",
            textColor: "#e8ecf4",
            fontFamily: '"Segoe UI Variable", "Segoe UI", sans-serif',
          },
        });
        const out = await mermaid.render(id, source);
        if (!cancelled) setSvg(out.svg);
      } catch {
        // A failed render leaves its scratch node behind in <body>.
        document.getElementById(`d${id}`)?.remove();
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, source]);

  if (svg) {
    return (
      <figure
        className="my-4 flex justify-center overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface)] p-3 [&_svg]:h-auto [&_svg]:max-w-full"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    );
  }
  return (
    <div>
      <pre>
        <code>{source}</code>
      </pre>
      {failed && (
        <p className="-mt-2 mb-3 text-[11px] text-[var(--ink-3)]">
          This diagram did not parse, so its source is shown. Obsidian may still draw it.
        </p>
      )}
    </div>
  );
}
