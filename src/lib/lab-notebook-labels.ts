// Client-safe labels for the lab notebook. Kept out of labNotebook.ts, which
// spawns Python - importing even a constant from it into a client component
// pulls node:child_process into the browser bundle (the agent-models lesson).
export const ASSAY_LABEL: Record<string, string> = {
  flow: "Flow cytometry",
  ultrasound: "Ultrasound",
  "primer-design": "Primer design",
  bench: "Bench",
  computational: "Computational",
  other: "Other",
};
