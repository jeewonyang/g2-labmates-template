import { Badge } from "@/components/ui/Badge";
import { ASSAY_LABEL } from "@/lib/lab-notebook-labels";

const OUTCOME_TONE: Record<string, "gray" | "green" | "amber" | "red" | "blue" | "purple"> = {
  positive: "green",
  negative: "red",
  mixed: "amber",
  inconclusive: "purple",
  "technical-failure": "red",
  pending: "gray",
};

/** Assay, outcome, and draft state: one drawing, on the list and on the entry. */
export function NotebookBadges({ assay, outcome, status }: { assay: string; outcome: string; status: string }) {
  return (
    <span className="flex shrink-0 items-center gap-1.5">
      <Badge>{ASSAY_LABEL[assay] ?? assay}</Badge>
      <Badge tone={OUTCOME_TONE[outcome] ?? "gray"}>{outcome}</Badge>
      {status === "draft" && <Badge tone="blue">draft</Badge>}
    </span>
  );
}
