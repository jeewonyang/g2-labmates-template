"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card, Button } from "@/components/ui/primitives";
import { ChevronDown, ChevronRight, Pencil, Save, ShieldAlert } from "lucide-react";
import type {
  ReviewBatch,
  Job,
  TriageAction,
  TriageProposal,
} from "@/lib/services/ledger";

/**
 * Batch approval: one decision per destination instead of one per file.
 *
 * Confidential and leave-in-inbox batches set requiresPerItem, so bulk approve
 * is withheld and each item must be expanded and approved individually — the
 * same rule the classifier and taxonomy.md enforce.
 */
export function ReviewBatches({ batches }: { batches: ReviewBatch[] }) {
  const router = useRouter();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(
    action: "approve" | "reject" | "revise",
    jobIds: string[],
    key: string,
    proposal?: TriageProposal,
  ) {
    setBusy(key);
    setError(null);
    try {
      const res = await fetch("/api/ops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, jobIds, proposal }),
      });
      if (!res.ok && res.status !== 207) {
        const body = await res.json().catch(() => ({}));
        setError(body.error ?? `request failed (${res.status})`);
      } else {
        router.refresh();
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  if (batches.length === 0) return null;

  return (
    <div className="space-y-3">
      {error && (
        <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
          {error}
        </div>
      )}
      {batches.map((b) => {
        const isOpen = open[b.key];
        const ids = b.jobs.map((j) => j.job);
        return (
          <Card key={b.key} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <button
                  onClick={() => setOpen((o) => ({ ...o, [b.key]: !o[b.key] }))}
                  className="flex items-center gap-1.5 text-left font-medium text-[var(--ink)]"
                >
                  {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  <span className="font-mono text-sm">{b.key}</span>
                </button>
                <p className="mt-1 text-xs text-[var(--ink-3)]">
                  {b.count} file{b.count === 1 ? "" : "s"} · mean confidence{" "}
                  {b.meanConfidence.toFixed(2)}
                </p>
                {b.requiresPerItem && (
                  <p className="mt-1 flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400">
                    <ShieldAlert className="h-3.5 w-3.5" />
                    {b.vault === "Confidential"
                      ? "Confidential — approve individually"
                      : b.bucket === "10_Projects" && b.folderMode === "create"
                        ? "New project — approve individually"
                        : "Unclassified — needs a destination"}
                  </p>
                )}
              </div>

              {!b.requiresPerItem && (
                <div className="flex shrink-0 gap-2">
                  <Button
                    onClick={() => act("approve", ids, b.key)}
                    disabled={busy === b.key}
                  >
                    {busy === b.key
                      ? "Working…"
                      : b.folderMode === "create"
                        ? `Create folder + reclassify ${b.count}`
                        : `Approve ${b.count}`}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => act("reject", ids, b.key)}
                    disabled={busy === b.key}
                  >
                    Reject
                  </Button>
                </div>
              )}
            </div>

            {isOpen && (
              <ul className="mt-3 space-y-2 border-t border-[var(--rule)] pt-3">
                {b.jobs.map((j) => (
                    <JobRow key={j.job} job={j} busy={busy === j.job} onAct={act} />
                ))}
              </ul>
            )}
          </Card>
        );
      })}
    </div>
  );
}

const BUCKETS: Record<string, string[]> = {
  "G2OS-Staging": ["10_Projects", "20_Areas", "30_Resources", "90_Archive"],
  "Research-Private": ["10_Projects", "20_Areas", "30_Resources", "90_Archive"],
  Confidential: ["20_Areas", "40_People", "90_Archive"],
  Finance: ["20_Areas", "30_Resources", "90_Archive"],
  "leave-in-inbox": ["none"],
};
// Example project folders inside a vault's `10_Projects/`. Replace these with
// the folder names you actually use — they only populate the picker.
const PROJECTS = ["00_Admin", "01_Project-One", "02_Project-Two"];
const CONTEXTS = [
  "office",
  "lab",
  "computer",
  "phone",
  "home",
  "errand",
  "anywhere",
  "creative",
  "routine",
];

function JobRow({
  job,
  busy,
  onAct,
}: {
  job: Job;
  busy: boolean;
  onAct: (
    a: "approve" | "reject" | "revise",
    ids: string[],
    key: string,
    proposal?: TriageProposal,
  ) => void;
}) {
  const p = (job.proposal ?? {}) as TriageProposal;
  const [editing, setEditing] = useState(false);
  const [vault, setVault] = useState(
    p.vault && p.vault in BUCKETS ? p.vault : "Research-Private",
  );
  const availableBuckets = BUCKETS[vault] ?? [];
  const [bucket, setBucket] = useState(
    availableBuckets.includes(p.bucket ?? "") ? p.bucket! : availableBuckets[0],
  );
  const [project, setProject] = useState(p.project ?? PROJECTS[0]);
  const [folderMode, setFolderMode] = useState<
    "bucket-root" | "existing" | "create"
  >(p.folder_mode ?? ((p.folder ?? p.project) ? "existing" : "bucket-root"));
  const [folder, setFolder] = useState(p.folder ?? p.project ?? "");
  const primaryAction = p.actions?.find(
    (action): action is TriageAction =>
      Boolean(action && action.kind && action.kind !== "none"),
  );
  const [actionKind, setActionKind] = useState<
    "task" | "note" | "resource" | "none"
  >(primaryAction?.kind ?? "none");
  const [actionTitle, setActionTitle] = useState(
    primaryAction?.title ?? p.title ?? "",
  );
  const [actionContext, setActionContext] = useState(
    primaryAction?.context ?? "",
  );
  const [actionDueDate, setActionDueDate] = useState(
    primaryAction?.due_date?.slice(0, 10) ?? "",
  );
  const proposedFolderMode =
    p.folder_mode ?? ((p.folder ?? p.project) ? "existing" : "bucket-root");
  const editDestinationValid =
    vault === "leave-in-inbox"
      ? bucket === "none" && folderMode === "bucket-root"
      : bucket !== "none" &&
        (folderMode === "bucket-root" || Boolean(folder.trim())) &&
        (bucket !== "10_Projects" ||
          (folderMode !== "bucket-root" && Boolean(project.trim())));
  const validDestination =
    Boolean(p.vault && p.vault in BUCKETS) &&
    Boolean(p.bucket && BUCKETS[p.vault!]?.includes(p.bucket)) &&
    p.vault !== "leave-in-inbox" &&
    p.bucket !== "none" &&
    (p.bucket !== "10_Projects" || Boolean(p.project)) &&
    (proposedFolderMode === "bucket-root" || Boolean(p.folder ?? p.project));
  const src =
    typeof job.payload === "object" && job.payload !== null
      ? String((job.payload as { path?: string }).path ?? "")
      : "";
  const projectListId = `known-project-folders-${job.job}`;
  return (
    <li className="flex min-w-0 flex-wrap items-start justify-between gap-2 text-sm">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-[var(--ink)]">
          {p.title || src || "Untitled capture"}
        </p>
        {p.title && src && (
          <p className="truncate font-mono text-[10px] text-[var(--ink-3)]">{src}</p>
        )}
        {p.reason && (
          <p className="mt-0.5 text-xs italic text-[var(--ink-3)]">{p.reason}</p>
        )}
        {primaryAction && (
          <p className="mt-1 text-xs text-[var(--ink-2)]">
            <span className="font-medium capitalize">{primaryAction.kind}</span>
            {" · "}
            {primaryAction.title || p.title || "Untitled"}
            {primaryAction.context ? ` · @${primaryAction.context}` : " · needs context"}
            {primaryAction.due_date ? ` · due ${primaryAction.due_date.slice(0, 10)}` : ""}
          </p>
        )}
        {job.review_verdict === "action-needs-human" && (
          <p className="mt-1 text-xs font-medium text-amber-700 dark:text-amber-400">
            The file destination is resolved, but the proposed task/note metadata is inconsistent.
            Edit the action, then approve.
          </p>
        )}
        {p.folder_mode === "create" && p.folder && (
          <p className="mt-1 text-xs font-medium text-amber-700 dark:text-amber-400">
            New folder: {p.folder} — approval creates it, then reclassifies this item.
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span className="text-xs tabular-nums text-[var(--ink-3)]">
          {typeof p.confidence === "number" ? p.confidence.toFixed(2) : "—"}
        </span>
        <Button
          onClick={() => onAct("approve", [job.job], job.job)}
          disabled={busy || !validDestination}
          title={!validDestination ? "Choose a valid destination first" : undefined}
        >
          {p.folder_mode === "create" ? "Create + reclassify" : "Approve"}
        </Button>
        <Button variant="ghost" onClick={() => setEditing((value) => !value)} disabled={busy}>
          <Pencil className="h-3.5 w-3.5" />
          Edit
        </Button>
        <Button
          variant="ghost"
          onClick={() => onAct("reject", [job.job], job.job)}
          disabled={busy}
        >
          Reject
        </Button>
      </div>
      {editing && (
        <div className="basis-full rounded-[var(--radius-sm)] border bg-[var(--bg)] p-2.5">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-[var(--ink-3)]">
              Vault
              <select
                value={vault}
                onChange={(event) => {
                  const next = event.target.value;
                  setVault(next);
                  setBucket(BUCKETS[next][0]);
                  if (next === "leave-in-inbox") {
                    setFolderMode("bucket-root");
                    setFolder("");
                  }
                }}
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
              >
                {Object.keys(BUCKETS).map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-[var(--ink-3)]">
              Bucket
              <select
                value={bucket}
                onChange={(event) => {
                  const next = event.target.value;
                  setBucket(next);
                  if (next === "10_Projects" && folderMode === "bucket-root") {
                    setFolderMode("existing");
                    setFolder(project);
                  }
                }}
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
              >
                {availableBuckets.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-[var(--ink-3)]">
              Folder handling
              <select
                value={folderMode}
                onChange={(event) => {
                  const next = event.target.value as
                    "bucket-root" | "existing" | "create";
                  setFolderMode(next);
                  if (next === "bucket-root") setFolder("");
                }}
                disabled={vault === "leave-in-inbox"}
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)] disabled:opacity-50"
              >
                <option value="bucket-root">Use bucket root</option>
                <option value="existing">Use existing folder</option>
                <option value="create">Create, then reclassify</option>
              </select>
            </label>
            <label className="text-xs text-[var(--ink-3)]">
              Folder
              <input
                value={folder}
                onChange={(event) => {
                  setFolder(event.target.value);
                  if (bucket === "10_Projects") {
                    setProject(event.target.value.split(/[\\/]/)[0]);
                  }
                }}
                disabled={folderMode === "bucket-root"}
                placeholder="e.g. Imaging/Protocols"
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)] disabled:opacity-50"
              />
            </label>
          </div>
          {bucket === "10_Projects" && (
            <label className="mt-2 block text-xs text-[var(--ink-3)]">
              Project folder
              <input
                value={project}
                onChange={(event) => setProject(event.target.value)}
                list={projectListId}
                className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
              />
              <datalist id={projectListId}>
                {PROJECTS.map((value) => (
                  <option key={value} value={value} />
                ))}
              </datalist>
            </label>
          )}
          {primaryAction && (
            <div className="mt-3 border-t border-[var(--rule)] pt-3">
              <p className="mb-2 text-xs font-medium text-[var(--ink-2)]">
                Captured action
              </p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <label className="text-xs text-[var(--ink-3)]">
                  Type
                  <select
                    value={actionKind}
                    onChange={(event) =>
                      setActionKind(
                        event.target.value as "task" | "note" | "resource" | "none",
                      )
                    }
                    className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
                  >
                    <option value="task">Next-action task</option>
                    <option value="note">Note</option>
                    <option value="resource">Resource</option>
                    <option value="none">No dashboard item</option>
                  </select>
                </label>
                <label className="text-xs text-[var(--ink-3)]">
                  Title
                  <input
                    value={actionTitle}
                    onChange={(event) => setActionTitle(event.target.value)}
                    className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)]"
                  />
                </label>
                <label className="text-xs text-[var(--ink-3)]">
                  Context
                  <select
                    value={actionContext}
                    onChange={(event) => setActionContext(event.target.value)}
                    disabled={actionKind !== "task"}
                    className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)] disabled:opacity-50"
                  >
                    <option value="">Needs context</option>
                    {CONTEXTS.map((value) => (
                      <option key={value} value={value}>@{value}</option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-[var(--ink-3)]">
                  Due date
                  <input
                    type="date"
                    value={actionDueDate}
                    onChange={(event) => setActionDueDate(event.target.value)}
                    disabled={actionKind !== "task"}
                    className="mt-1 w-full rounded border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)] disabled:opacity-50"
                  />
                </label>
              </div>
            </div>
          )}
          <div className="mt-2 flex justify-end">
            <Button
              onClick={() => {
                onAct("revise", [job.job], job.job, {
                  ...p,
                  vault,
                  bucket,
                  project: bucket === "10_Projects" ? project : null,
                  folder: folderMode === "bucket-root" ? null : folder.trim(),
                  folder_mode: folderMode,
                  folder_rationale:
                    folderMode === "create"
                      ? "New durable category chosen manually in G2"
                      : "Destination corrected manually in G2",
                  reason: "Corrected manually in G2",
                  actions: primaryAction
                    ? [{
                        ...primaryAction,
                        kind: actionKind,
                        title: actionTitle.trim() || p.title || "Captured item",
                        context: actionKind === "task" ? actionContext || null : null,
                        due_date: actionKind === "task" ? actionDueDate || null : null,
                        scheduled_date:
                          actionKind === "task" ? primaryAction.scheduled_date ?? null : null,
                        calendar_event:
                          actionKind === "task"
                            ? Boolean(primaryAction.calendar_event)
                            : false,
                      }]
                    : p.actions,
                });
                setEditing(false);
              }}
              disabled={busy || !editDestinationValid}
            >
              <Save className="h-3.5 w-3.5" />
              Save correction
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}
