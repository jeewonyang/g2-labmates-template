"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/primitives";
import { DateTimeField, Field, Input, Select, Textarea } from "@/components/ui/inputs";
import {
  createAreaAction,
  createGoalAction,
  createNoteAction,
  createProjectAction,
  createResourceAction,
  createTaskAction,
} from "@/lib/actions";
import {
  AREA_TYPES,
  NOTE_TYPES,
  NOTE_TYPE_META,
  PRIORITIES,
  PRIORITY_META,
  RESOURCE_TYPES,
  RESOURCE_TYPE_META,
  TASK_CONTEXTS,
  TASK_CONTEXT_META,
} from "@/lib/types";
import { joinDateTime } from "@/lib/utils";
import { useFormActionError } from "@/components/forms/useFormActionError";

export type Option = { id: string; title: string };
export type ProjectOption = Option & { areaId?: string | null };

function useDialog(defaultOpen = false) {
  const [open, setOpen] = useState(defaultOpen);
  return { open, setOpen };
}

function TriggerButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button variant="primary" size="sm" onClick={onClick}>
      <Plus className="h-4 w-4" />
      {label}
    </Button>
  );
}

// ---------------- Task ----------------
export function NewTaskButton({
  projects = [],
  areas = [],
  defaultProjectId,
  defaultAreaId,
  label = "New task",
  openOnMount = false,
}: {
  projects?: ProjectOption[];
  areas?: Option[];
  defaultProjectId?: string;
  defaultAreaId?: string;
  label?: string;
  openOnMount?: boolean;
}) {
  const { open, setOpen } = useDialog(openOnMount);
  return (
    <>
      <TriggerButton label={label} onClick={() => setOpen(true)} />
      <TaskCreateDialog
        open={open}
        onClose={() => setOpen(false)}
        projects={projects}
        areas={areas}
        defaultProjectId={defaultProjectId}
        defaultAreaId={defaultAreaId}
      />
    </>
  );
}

/**
 * The new-task form without its own trigger, so a surface that already knows
 * *when* the task belongs — a calendar day cell — can open it with that date
 * already filled in instead of making you retype it.
 *
 * `defaultDueDate` seeds the form on each open rather than being applied once:
 * the same mounted dialog is reused for every day of the week, so the date has
 * to follow the cell that was pressed.
 */
export function TaskCreateDialog({
  open,
  onClose,
  projects = [],
  areas = [],
  defaultProjectId,
  defaultAreaId,
  defaultDueDate = "",
  dateLabel,
}: {
  open: boolean;
  onClose: () => void;
  projects?: ProjectOption[];
  areas?: Option[];
  defaultProjectId?: string;
  defaultAreaId?: string;
  defaultDueDate?: string;
  dateLabel?: string;
}) {
  const router = useRouter();
  const setOpen = (next: boolean) => {
    if (!next) onClose();
  };
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const blank = () => ({
    title: "",
    priority: "medium",
    context: "",
    dueDate: defaultDueDate,
    scheduledDate: "",
    scheduledTime: "",
    projectId: defaultProjectId ?? "",
    areaId: defaultAreaId ?? "",
    status: defaultDueDate ? "scheduled" : "next",
  });
  const [form, setForm] = useState(blank);

  useEffect(() => {
    if (open) setForm(blank());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultDueDate]);
  const inheritedAreaId =
    projects.find((project) => project.id === form.projectId)?.areaId ??
    (form.projectId === defaultProjectId ? defaultAreaId : undefined);

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await createTaskAction({
        title: form.title,
        priority: form.priority,
        status: form.status,
        context: form.context || undefined,
        dueDate: form.dueDate || undefined,
        scheduledDate: joinDateTime(form.scheduledDate, form.scheduledTime) || undefined,
        projectId: form.projectId || undefined,
        areaId: form.areaId || undefined,
      });
      setForm(blank());
      setOpen(false);
      router.refresh();
    }));
  };

  return (
    <>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={dateLabel ? `New task — ${dateLabel}` : "New task"}
        error={error}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending || !form.title.trim()}>
              Create task
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Title">
            <Input
              autoFocus
              maxLength={300}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="What needs to be done?"
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Priority">
              <Select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}
              </Select>
            </Field>
            <Field label="Due date">
              <Input type="date" value={form.dueDate} onChange={(e) => setForm({ ...form, dueDate: e.target.value })} />
            </Field>
            <Field label="Context">
              <Select value={form.context} onChange={(e) => setForm({ ...form, context: e.target.value })}>
                <option value="">None</option>
                {TASK_CONTEXTS.map((c) => <option key={c} value={c}>{TASK_CONTEXT_META[c].label}</option>)}
              </Select>
            </Field>
            <Field label="Status">
              <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                <option value="next">Next action</option>
                <option value="inbox">Inbox</option>
                <option value="scheduled">Scheduled</option>
                <option value="waiting">Waiting</option>
                <option value="someday">Someday</option>
              </Select>
            </Field>
            <DateTimeField
              label="Action date"
              date={form.scheduledDate}
              time={form.scheduledTime}
              onChange={(date, time) => setForm({ ...form, scheduledDate: date, scheduledTime: date ? time : "" })}
            />
            {projects.length > 0 && (
              <Field label="Project">
                <Select
                  value={form.projectId}
                  onChange={(e) => {
                    const projectId = e.target.value;
                    const project = projects.find((item) => item.id === projectId);
                    setForm({
                      ...form,
                      projectId,
                      areaId:
                        projectId && project?.areaId
                          ? project.areaId
                          : projectId
                            ? ""
                            : form.areaId,
                    });
                  }}
                >
                  <option value="">None</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
                </Select>
              </Field>
            )}
            {areas.length > 0 && (
              <Field label={inheritedAreaId ? "Area (from project)" : "Area"}>
                <Select
                  value={inheritedAreaId ?? form.areaId}
                  disabled={Boolean(inheritedAreaId)}
                  onChange={(e) => setForm({ ...form, areaId: e.target.value })}
                >
                  <option value="">None</option>
                  {areas.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
                </Select>
                {inheritedAreaId && (
                  <p className="mt-1 text-[11px] text-[var(--ink-3)]">
                    Inherited automatically from the selected project.
                  </p>
                )}
              </Field>
            )}
          </div>
        </div>
      </Dialog>
    </>
  );
}

// ---------------- Project ----------------
export function NewProjectButton({
  areas = [],
  goals = [],
  openOnMount = false,
}: {
  areas?: Option[];
  goals?: Option[];
  openOnMount?: boolean;
}) {
  const router = useRouter();
  const { open, setOpen } = useDialog(openOnMount);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const [form, setForm] = useState({
    title: "", description: "", priority: "medium", areaId: "", goalId: "", targetDate: "",
  });

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      const p = await createProjectAction({
        title: form.title,
        description: form.description || undefined,
        priority: form.priority,
        status: "active",
        areaId: form.areaId || undefined,
        goalId: form.goalId || undefined,
        targetDate: form.targetDate || undefined,
      });
      setOpen(false);
      router.push(`/projects/${p.id}`);
    }));
  };

  return (
    <>
      <TriggerButton label="New project" onClick={() => setOpen(true)} />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="New project"
        error={error}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending || !form.title.trim()}>
              Create project
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Title">
            <Input autoFocus maxLength={300} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Project outcome" />
          </Field>
          <Field label="Description">
            <Textarea rows={2} maxLength={10_000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Priority">
              <Select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}
              </Select>
            </Field>
            <Field label="Target date">
              <Input type="date" value={form.targetDate} onChange={(e) => setForm({ ...form, targetDate: e.target.value })} />
            </Field>
            {areas.length > 0 && (
              <Field label="Area">
                <Select value={form.areaId} onChange={(e) => setForm({ ...form, areaId: e.target.value })}>
                  <option value="">None</option>
                  {areas.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
                </Select>
              </Field>
            )}
            {goals.length > 0 && (
              <Field label="Goal">
                <Select value={form.goalId} onChange={(e) => setForm({ ...form, goalId: e.target.value })}>
                  <option value="">None</option>
                  {goals.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
                </Select>
              </Field>
            )}
          </div>
        </div>
      </Dialog>
    </>
  );
}

// ---------------- Note ----------------
export function NewNoteButton({
  projects = [],
  areas = [],
  openOnMount = false,
}: {
  projects?: Option[];
  areas?: Option[];
  openOnMount?: boolean;
}) {
  const router = useRouter();
  const { open, setOpen } = useDialog(openOnMount);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const [form, setForm] = useState({
    title: "", contentMarkdown: "", type: "fleeting", projectId: "", areaId: "",
  });

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      const n = await createNoteAction({
        title: form.title,
        contentMarkdown: form.contentMarkdown || undefined,
        type: form.type,
        projectId: form.projectId || undefined,
        areaId: form.areaId || undefined,
      });
      setOpen(false);
      router.push(`/notes/${n.id}`);
    }));
  };

  return (
    <>
      <TriggerButton label="New note" onClick={() => setOpen(true)} />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="New note"
        error={error}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending || !form.title.trim()}>
              Create note
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Title">
            <Input autoFocus maxLength={300} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Note title" />
          </Field>
          <Field label="Content (markdown)">
            <Textarea rows={5} maxLength={200_000} value={form.contentMarkdown} onChange={(e) => setForm({ ...form, contentMarkdown: e.target.value })} placeholder="Write in markdown…" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <Select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {NOTE_TYPES.map((t) => <option key={t} value={t}>{NOTE_TYPE_META[t].label}</option>)}
              </Select>
            </Field>
            {projects.length > 0 && (
              <Field label="Project">
                <Select value={form.projectId} onChange={(e) => setForm({ ...form, projectId: e.target.value })}>
                  <option value="">None</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
                </Select>
              </Field>
            )}
            {areas.length > 0 && (
              <Field label="Area">
                <Select value={form.areaId} onChange={(e) => setForm({ ...form, areaId: e.target.value })}>
                  <option value="">None</option>
                  {areas.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
                </Select>
              </Field>
            )}
          </div>
        </div>
      </Dialog>
    </>
  );
}

// ---------------- Resource ----------------
export function NewResourceButton({
  areas = [],
  openOnMount = false,
}: {
  areas?: Option[];
  openOnMount?: boolean;
}) {
  const router = useRouter();
  const { open, setOpen } = useDialog(openOnMount);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const [form, setForm] = useState({ title: "", url: "", type: "article", summary: "", areaId: "" });

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await createResourceAction({
        title: form.title,
        url: form.url || undefined,
        type: form.type,
        summary: form.summary || undefined,
        status: "inbox",
        areaId: form.areaId || undefined,
      });
      setOpen(false);
      router.refresh();
    }));
  };

  return (
    <>
      <TriggerButton label="New resource" onClick={() => setOpen(true)} />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="New resource"
        error={error}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending || !form.title.trim()}>
              Save resource
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Title">
            <Input autoFocus maxLength={300} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="URL">
            <Input type="url" maxLength={2000} value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" />
          </Field>
          <Field label="Summary">
            <Textarea rows={2} maxLength={20_000} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <Select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {RESOURCE_TYPES.map((t) => <option key={t} value={t}>{RESOURCE_TYPE_META[t].label}</option>)}
              </Select>
            </Field>
            {areas.length > 0 && (
              <Field label="Area">
                <Select value={form.areaId} onChange={(e) => setForm({ ...form, areaId: e.target.value })}>
                  <option value="">None</option>
                  {areas.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
                </Select>
              </Field>
            )}
          </div>
        </div>
      </Dialog>
    </>
  );
}

// ---------------- Goal ----------------
export function NewGoalButton({ areas = [] }: { areas?: Option[] }) {
  const router = useRouter();
  const { open, setOpen } = useDialog(false);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const nowYear = new Date().getFullYear();
  const [form, setForm] = useState({ title: "", year: String(nowYear), quarter: "", areaId: "" });

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await createGoalAction({
        title: form.title,
        year: form.year ? Number(form.year) : undefined,
        quarter: form.quarter ? Number(form.quarter) : undefined,
        areaId: form.areaId || undefined,
      });
      setOpen(false);
      router.refresh();
    }));
  };

  return (
    <>
      <TriggerButton label="New goal" onClick={() => setOpen(true)} />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="New goal"
        error={error}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending || !form.title.trim()}>
              Create goal
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Title">
            <Input autoFocus maxLength={300} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Year">
              <Input type="number" value={form.year} onChange={(e) => setForm({ ...form, year: e.target.value })} />
            </Field>
            <Field label="Quarter">
              <Select value={form.quarter} onChange={(e) => setForm({ ...form, quarter: e.target.value })}>
                <option value="">—</option>
                <option value="1">Q1</option>
                <option value="2">Q2</option>
                <option value="3">Q3</option>
                <option value="4">Q4</option>
              </Select>
            </Field>
            {areas.length > 0 && (
              <Field label="Area">
                <Select value={form.areaId} onChange={(e) => setForm({ ...form, areaId: e.target.value })}>
                  <option value="">None</option>
                  {areas.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
                </Select>
              </Field>
            )}
          </div>
        </div>
      </Dialog>
    </>
  );
}

// ---------------- Area ----------------
export function NewAreaButton() {
  const router = useRouter();
  const { open, setOpen } = useDialog(false);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const [form, setForm] = useState({ title: "", description: "", type: "area" });

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await createAreaAction({
        title: form.title,
        description: form.description || undefined,
        type: form.type,
      });
      setOpen(false);
      router.refresh();
    }));
  };

  return (
    <>
      <TriggerButton label="New area" onClick={() => setOpen(true)} />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="New area"
        error={error}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={pending || !form.title.trim()}>
              Create area
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Title">
            <Input autoFocus maxLength={300} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Description">
            <Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field label="Type">
            <Select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              {AREA_TYPES.map((t) => <option key={t} value={t}>{t === "area" ? "Area (responsibility)" : "Resource (topic)"}</option>)}
            </Select>
          </Field>
        </div>
      </Dialog>
    </>
  );
}
