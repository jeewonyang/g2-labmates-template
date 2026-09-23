"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Pencil, Plus } from "lucide-react";
import { createNotebookEntryAction, nextExperimentIdAction, updateNotebookEntryAction } from "@/lib/actions";
import { Button } from "@/components/ui/primitives";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/inputs";
import { LabProjectPicker, labProjectReady, type LabProjectChoice } from "@/components/research/LabProjectPicker";

export type NotebookFormValues = {
  experimentId: string;
  date: string;
  name: string;
  summary: string;
  assay: string;
  outcome: string;
  status: string;
  inputPath: string;
  resultPath: string;
  introduction: string;
  objective: string;
  materialsMethods: string;
  result: string;
  conclusion: string;
  nextSteps: string;
};

const ASSAYS: Array<[string, string]> = [
  ["bench", "Bench"],
  ["flow", "Flow cytometry"],
  ["ultrasound", "Ultrasound"],
  ["primer-design", "Primer design"],
  ["computational", "Computational"],
  ["other", "Other"],
];
const OUTCOMES = ["pending", "positive", "negative", "mixed", "inconclusive", "technical-failure"];

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const BLANK: NotebookFormValues = {
  experimentId: "",
  date: "",
  name: "",
  summary: "",
  assay: "bench",
  outcome: "pending",
  status: "draft",
  inputPath: "",
  resultPath: "",
  introduction: "",
  objective: "",
  materialsMethods: "",
  result: "",
  conclusion: "",
  nextSteps: "",
};

/**
 * Create or edit a notebook entry by hand - the bench experiment with no
 * analysis job, or a correction to one an agent wrote. One dialog for both,
 * and one writer behind it (lab_notebook.py), so a hand-made entry has the
 * same five sections, title, and recorded data paths as a launched one.
 */
export function NotebookEntryDialog({
  projects,
  defaultProject,
  existing,
}: {
  projects: Array<{ code: string }>;
  defaultProject?: string;
  existing?: { projectCode: string; entryName: string; values: NotebookFormValues };
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [project, setProject] = useState<LabProjectChoice>(() =>
    existing
      ? { code: existing.projectCode, isNew: false }
      : projects.length
        ? { code: defaultProject || projects[0].code, isNew: false }
        : { code: "", isNew: true },
  );
  const projectCode = project.code.trim();
  const [form, setForm] = useState<NotebookFormValues>(existing?.values ?? BLANK);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  const set =
    (key: keyof NotebookFormValues) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm((f) => ({ ...f, [key]: e.target.value }));

  async function suggestId(code: string) {
    try {
      const id = await nextExperimentIdAction(code);
      setForm((f) => ({ ...f, experimentId: id }));
    } catch {
      // leave it blank; the writer allocates one
    }
  }

  function show() {
    setError(null);
    if (!existing) {
      setForm({ ...BLANK, date: today() });
      if (project.isNew) setForm((f) => ({ ...f, experimentId: "EXP-001" }));
      else if (projectCode) void suggestId(projectCode);
    }
    setOpen(true);
  }

  function save() {
    setError(null);
    const shared = {
      name: form.name,
      summary: form.summary,
      assay: form.assay,
      outcome: form.outcome,
      status: form.status,
      inputPath: form.inputPath,
      resultPath: form.resultPath,
      introduction: form.introduction,
      objective: form.objective,
      materialsMethods: form.materialsMethods,
      result: form.result,
      conclusion: form.conclusion,
      nextSteps: form.nextSteps
        .split("\n")
        .map((l) => l.replace(/^\s*(?:[-*]\s*)?(?:\[[ xX]\]\s*)?/, "").trim())
        .filter(Boolean),
    };
    start(async () => {
      try {
        const saved = existing
          ? await updateNotebookEntryAction({ projectCode, entryName: existing.entryName, ...shared })
          : await createNotebookEntryAction({
              projectCode,
              newProject: project.isNew || undefined,
              experimentId: form.experimentId,
              date: form.date,
              ...shared,
            });
        setOpen(false);
        router.push(`/research/notebook/${saved.projectCode ?? projectCode}/${saved.title}`);
        router.refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not save this entry.");
      }
    });
  }

  const title = existing
    ? `Edit ${existing.entryName}`
    : `New entry · ${form.experimentId || "EXP-…"}_${projectCode}_${form.date || today()}`;

  return (
    <>
      {existing ? (
        <Button size="sm" onClick={show}>
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
      ) : (
        <Button variant="primary" size="sm" onClick={show}>
          <Plus className="h-3.5 w-3.5" /> New entry
        </Button>
      )}
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={title}
        error={error}
        footer={
          <>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={save}
              disabled={
                pending || !form.inputPath.trim() || !form.resultPath.trim() || !labProjectReady(project, projects)
              }
            >
              {pending ? "Saving…" : "Save entry"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {!existing && (
            <div className="grid gap-3 sm:grid-cols-3">
              <LabProjectPicker
                projects={projects}
                value={project}
                onChange={(next) => {
                  setProject(next);
                  // A new project's notebook starts at EXP-001.
                  if (next.isNew) setForm((f) => ({ ...f, experimentId: "EXP-001" }));
                  else void suggestId(next.code);
                }}
              />
              <Field label="Experiment ID">
                <Input value={form.experimentId} onChange={set("experimentId")} placeholder="EXP-001" />
              </Field>
              <Field label="Date">
                <Input type="date" value={form.date} onChange={set("date")} />
              </Field>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Assay">
              <Select value={form.assay} onChange={set("assay")}>
                {ASSAYS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Outcome">
              <Select value={form.outcome} onChange={set("outcome")}>
                {OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Status">
              <Select value={form.status} onChange={set("status")}>
                <option value="draft">draft</option>
                <option value="final">final</option>
              </Select>
            </Field>
          </div>
          <Field label="Name">
            <Input value={form.name} onChange={set("name")} placeholder="Short title of the experiment" />
          </Field>
          <Field label="One-line summary">
            <Input value={form.summary} onChange={set("summary")} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Input data path (required)">
              <Input value={form.inputPath} onChange={set("inputPath")} spellCheck={false} />
            </Field>
            <Field label="Result data path (required)">
              <Input value={form.resultPath} onChange={set("resultPath")} spellCheck={false} />
            </Field>
          </div>
          <Field label="Introduction">
            <Textarea rows={3} value={form.introduction} onChange={set("introduction")} />
          </Field>
          <Field label="Objective">
            <Textarea rows={2} value={form.objective} onChange={set("objective")} />
          </Field>
          <Field label="Materials & Methods">
            <Textarea rows={5} value={form.materialsMethods} onChange={set("materialsMethods")} />
          </Field>
          <Field label="Result">
            <Textarea rows={5} value={form.result} onChange={set("result")} />
          </Field>
          <Field label="Conclusion">
            <Textarea rows={3} value={form.conclusion} onChange={set("conclusion")} />
          </Field>
          <Field label="Next steps, one per line">
            <Textarea rows={3} value={form.nextSteps} onChange={set("nextSteps")} />
          </Field>
        </div>
      </Dialog>
    </>
  );
}
