"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { format } from "date-fns";
import { Check, Pencil, Star, Trash2 } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/primitives";
import { DateTimeField, Field, Input, Select, Textarea } from "@/components/ui/inputs";
import {
  getPickerOptionsAction,
  archiveAreaAction,
  archiveGoalAction,
  archiveProjectAction,
  archiveResourceAction,
  deleteTaskAction,
  updateAreaAction,
  updateGoalAction,
  setProjectStatusAction,
  updateProjectAction,
  updateResourceAction,
  updateTaskAction,
} from "@/lib/actions";
import {
  AREA_HEALTH_META,
  AREA_TYPES,
  GOAL_STATUSES,
  GOAL_STATUS_META,
  PRIORITIES,
  PRIORITY_META,
  PROJECT_STATUSES,
  PROJECT_STATUS_META,
  RESOURCE_STATUSES,
  RESOURCE_STATUS_META,
  RESOURCE_TYPES,
  RESOURCE_TYPE_META,
  TASK_CONTEXTS,
  TASK_CONTEXT_META,
  TASK_STATUSES,
  TASK_STATUS_META,
  type AreaHealth,
} from "@/lib/types";
import { formatTimeInput, joinDateTime, parseDateInput } from "@/lib/utils";
import { useFormActionError } from "@/components/forms/useFormActionError";

type Option = { id: string; title: string };
type ProjectOption = Option & { areaId: string | null };
type PickerOptions = { projects: ProjectOption[]; areas: Option[]; goals: Option[] };

/** Load project/area/goal pickers lazily, only once the dialog is opened. */
function usePickerOptions(open: boolean): PickerOptions | null {
  const [opts, setOpts] = useState<PickerOptions | null>(null);
  useEffect(() => {
    if (!open || opts) return;
    getPickerOptionsAction()
      .then(setOpts)
      .catch(() => setOpts({ projects: [], areas: [], goals: [] }));
  }, [open, opts]);
  return opts;
}

/** Selects for linking an entry to a project/area/goal, with a loading state. */
function LinkSelect({
  label,
  value,
  options,
  disabled = false,
  onChange,
}: {
  label: string;
  value: string;
  options: Option[] | undefined;
  disabled?: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <Field label={label}>
      <Select
        value={options ? value : ""}
        disabled={!options || disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {options ? (
          <>
            <option value="">None</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>{o.title}</option>
            ))}
          </>
        ) : (
          <option value="">Loading…</option>
        )}
      </Select>
    </Field>
  );
}

const toDateInput = (d: Date | string | null | undefined) =>
  d ? format(new Date(d), "yyyy-MM-dd") : "";

const toTimeInput = (d: Date | string | null | undefined) =>
  d ? formatTimeInput(new Date(d)) : "";

/**
 * Icon-trigger styling for list cards. The default icon trigger is revealed on
 * hover, which is right for dense task rows on a desktop but leaves the control
 * unreachable on a tablet they read the dashboard from over the tailnet — there
 * is no hover there. Card triggers stay visible and muted instead.
 */
export const CARD_EDIT_TRIGGER =
  "shrink-0 rounded p-1 text-[var(--ink-3)] opacity-70 transition-opacity hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] hover:opacity-100 focus-visible:opacity-100";

function EditTrigger({
  onClick,
  iconOnly = false,
  className,
}: {
  onClick: () => void;
  iconOnly?: boolean;
  className?: string;
}) {
  if (iconOnly) {
    return (
      <button
        aria-label="Edit"
        onClick={onClick}
        className={
          className ??
          "shrink-0 rounded p-1 text-[var(--ink-3)] opacity-0 transition-opacity hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] focus-visible:opacity-100 group-hover:opacity-100"
        }
      >
        <Pencil className="h-4 w-4" />
      </button>
    );
  }
  return (
    <Button variant="secondary" size="sm" onClick={onClick} className={className}>
      <Pencil className="h-3.5 w-3.5" />
      Edit
    </Button>
  );
}

/**
 * Delete control for the edit dialogs. Every one of these archives rather than
 * hard-deletes — the row stays on /archive — so the confirm text says so
 * plainly instead of implying the entry is gone for good.
 */
function DeleteFooterButton({
  label,
  pending,
  onDelete,
}: {
  label: string;
  pending: boolean;
  onDelete: () => void;
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onDelete}
      disabled={pending}
      className="mr-auto text-[var(--red)]"
    >
      <Trash2 className="h-3.5 w-3.5" />
      {label}
    </Button>
  );
}

/** Confirm, archive, then land the user back on the list. */
function useArchiveFlow(
  start: React.TransitionStartFunction,
  listHref: string,
  onClose: () => void,
  run: (work: () => Promise<void>) => Promise<void>,
) {
  const router = useRouter();
  return (title: string, noun: string, archive: () => Promise<void>) => {
    if (
      !window.confirm(
        `Delete "${title}"? The ${noun} moves to the archive and stays recoverable.`,
      )
    ) {
      return;
    }
    start(() => run(async () => {
      await archive();
      onClose();
      router.push(listHref);
      router.refresh();
    }));
  };
}

/**
 * A pill toggle for the two task states that are decisions rather than fields.
 *
 * Marking done and starring the day's one thing were reachable only from a list
 * row — the Status select could reach "completed", but nothing in the dialog
 * could set the highlight, so opening a task to edit it meant closing it again
 * to star it. Rendered as pills rather than checkboxes to match the check and
 * star affordances on the task rows these mirror.
 */
function StateToggle({
  on,
  onChange,
  icon,
  label,
  color,
  disabled = false,
  title,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  icon: React.ReactNode;
  label: string;
  color: string;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      disabled={disabled}
      aria-pressed={on}
      title={title}
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50"
      style={
        on
          ? { borderColor: color, color, background: "var(--surface-2)" }
          : { color: "var(--ink-3)" }
      }
    >
      {icon}
      {label}
    </button>
  );
}

function SaveFooter({
  pending,
  disabled,
  onCancel,
  onSave,
}: {
  pending: boolean;
  disabled: boolean;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <>
      <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
      <Button variant="primary" size="sm" onClick={onSave} disabled={pending || disabled}>
        Save changes
      </Button>
    </>
  );
}

// ---------------- Task ----------------
export type EditableTask = {
  id: string;
  title: string;
  status: string;
  priority: string;
  context: string | null;
  isHighlight?: boolean;
  dueDate: Date | string | null;
  scheduledDate: Date | string | null;
  project?: { id: string } | null;
  area?: { id: string } | null;
};

export function EditTaskButton({ task, iconOnly = true }: { task: EditableTask; iconOnly?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <EditTrigger iconOnly={iconOnly} onClick={() => setOpen(true)} />
      <TaskEditDialog task={task} open={open} onClose={() => setOpen(false)} />
    </>
  );
}

/**
 * The task editor without its own trigger, so any surface — a calendar cell, a
 * highlight row — can open it in place instead of navigating to /tasks.
 * Remounted per task via `key` by callers, which is what re-seeds the form.
 */
export function TaskEditDialog({
  task,
  open,
  onClose,
}: {
  task: EditableTask;
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const options = usePickerOptions(open);

  const initial = () => ({
    title: task.title,
    status: task.status,
    priority: task.priority,
    context: task.context ?? "",
    dueDate: toDateInput(task.dueDate),
    scheduledDate: toDateInput(task.scheduledDate),
    scheduledTime: toTimeInput(task.scheduledDate),
    projectId: task.project?.id ?? "",
    areaId: task.area?.id ?? "",
    isHighlight: Boolean(task.isHighlight),
  });
  const [form, setForm] = useState(initial);
  const done = form.status === "completed";
  const inheritedAreaId = options?.projects.find(
    (project) => project.id === form.projectId,
  )?.areaId;

  // Re-seed on each open so a cancelled edit does not leave stale text behind
  // the next time this dialog is shown for the same task.
  useEffect(() => {
    if (open) setForm(initial());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, task.id]);

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await updateTaskAction(task.id, {
        title: form.title,
        status: form.status,
        priority: form.priority,
        context: form.context,
        dueDate: form.dueDate || null,
        scheduledDate: joinDateTime(form.scheduledDate, form.scheduledTime) || null,
        projectId: form.projectId || null,
        areaId: form.areaId || null,
        isHighlight: form.isHighlight,
      });
      onClose();
      router.refresh();
    }));
  };

  const deleteTask = () => {
    if (!window.confirm(
      `Delete "${form.title}"? It will move to the archive and remain recoverable.`,
    )) return;
    start(() => run(async () => {
      await deleteTaskAction(task.id);
      onClose();
      router.refresh();
    }));
  };

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        title="Edit task"
        error={error}
        footer={
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={deleteTask}
              disabled={pending}
              className="mr-auto text-[var(--red)]"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </Button>
            <SaveFooter
              pending={pending}
              disabled={!form.title.trim()}
              onCancel={onClose}
              onSave={submit}
            />
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
            />
          </Field>

          <div className="flex flex-wrap items-center gap-2">
            <StateToggle
              on={done}
              color="var(--green)"
              icon={<Check className="h-3.5 w-3.5" />}
              label={done ? "Completed" : "Mark complete"}
              title="Completing also clears the highlight — a finished task is not today's one thing."
              onChange={(next) =>
                setForm({
                  ...form,
                  // Restore to a sensible open state rather than whatever it
                  // was: previousStatus lives server-side, and guessing here
                  // would fight it.
                  status: next ? "completed" : "next",
                  isHighlight: next ? false : form.isHighlight,
                })
              }
            />
            <StateToggle
              on={form.isHighlight}
              color="var(--amber)"
              disabled={done}
              icon={
                <Star
                  className="h-3.5 w-3.5"
                  fill={form.isHighlight ? "currentColor" : "none"}
                />
              }
              label="Today's highlight"
              title={
                done
                  ? "A completed task cannot be today's highlight."
                  : "Star this as the one thing that matters most today. Any other highlight is cleared."
              }
              onChange={(next) => setForm({ ...form, isHighlight: next })}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Status">
              <Select
                value={form.status}
                onChange={(e) =>
                  setForm({
                    ...form,
                    status: e.target.value,
                    isHighlight:
                      e.target.value === "completed" ? false : form.isHighlight,
                  })
                }
              >
                {TASK_STATUSES.map((s) => <option key={s} value={s}>{TASK_STATUS_META[s].label}</option>)}
              </Select>
            </Field>
            <Field label="Priority">
              <Select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}
              </Select>
            </Field>
            <Field label="Context">
              <Select value={form.context} onChange={(e) => setForm({ ...form, context: e.target.value })}>
                <option value="">None</option>
                {TASK_CONTEXTS.map((c) => <option key={c} value={c}>{TASK_CONTEXT_META[c].label}</option>)}
              </Select>
            </Field>
            <Field label="Due date">
              <Input type="date" value={form.dueDate} onChange={(e) => setForm({ ...form, dueDate: e.target.value })} />
            </Field>
            <DateTimeField
              label="Action date"
              date={form.scheduledDate}
              time={form.scheduledTime}
              onChange={(date, time) => setForm({ ...form, scheduledDate: date, scheduledTime: date ? time : "" })}
            />
            <LinkSelect
              label="Project"
              value={form.projectId}
              options={options?.projects}
              onChange={(projectId) => {
                const project = options?.projects.find((item) => item.id === projectId);
                setForm({
                  ...form,
                  projectId,
                  areaId: projectId ? project?.areaId ?? "" : form.areaId,
                });
              }}
            />
            <div>
              <LinkSelect
                label={inheritedAreaId ? "Area (from project)" : "Area"}
                value={inheritedAreaId ?? form.areaId}
                options={options?.areas}
                disabled={Boolean(inheritedAreaId)}
                onChange={(areaId) => setForm({ ...form, areaId })}
              />
              {inheritedAreaId && (
                <p className="-mt-2 text-[11px] text-[var(--ink-3)]">
                  Inherited automatically from the selected project.
                </p>
              )}
            </div>
          </div>
        </div>
      </Dialog>
    </>
  );
}

// ---------------- Project ----------------
export function EditProjectButton({
  project,
  iconOnly = false,
}: {
  iconOnly?: boolean;
  project: {
    id: string;
    title: string;
    description: string | null;
    priority: string;
    startDate: Date | string | null;
    targetDate: Date | string | null;
    areaId: string | null;
    goalId: string | null;
    status?: string;
  };
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const options = usePickerOptions(open);

  const initial = () => ({
    status: project.status ?? "active",
    title: project.title,
    description: project.description ?? "",
    priority: project.priority,
    startDate: toDateInput(project.startDate),
    targetDate: toDateInput(project.targetDate),
    areaId: project.areaId ?? "",
    goalId: project.goalId ?? "",
  });
  const [form, setForm] = useState(initial);
  const archive = useArchiveFlow(start, "/projects", () => setOpen(false), run);

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await updateProjectAction(project.id, {
        title: form.title,
        description: form.description,
        priority: form.priority,
        startDate: form.startDate || null,
        targetDate: form.targetDate || null,
        areaId: form.areaId || null,
        goalId: form.goalId || null,
      });
      // Status goes through setProjectStatus, which keeps completedAt and
      // archivedAt in step - the plain update does not.
      if (project.status !== undefined && form.status !== project.status) {
        await setProjectStatusAction(project.id, form.status);
      }
      setOpen(false);
      router.refresh();
    }));
  };

  return (
    <>
      <EditTrigger
        iconOnly={iconOnly}
        className={iconOnly ? CARD_EDIT_TRIGGER : undefined}
        onClick={() => { setForm(initial()); setOpen(true); }}
      />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Edit project"
        error={error}
        footer={
          <>
            <DeleteFooterButton
              label="Delete"
              pending={pending}
              onDelete={() =>
                archive(form.title, "project", () => archiveProjectAction(project.id))
              }
            />
            <SaveFooter pending={pending} disabled={!form.title.trim()} onCancel={() => setOpen(false)} onSave={submit} />
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Title">
            <Input autoFocus maxLength={300} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Description">
            <Textarea rows={3} maxLength={10_000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            {project.status !== undefined && (
              <Field label="Status">
                <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {PROJECT_STATUSES.map((s) => <option key={s} value={s}>{PROJECT_STATUS_META[s].label}</option>)}
                </Select>
              </Field>
            )}
            <Field label="Priority">
              <Select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}
              </Select>
            </Field>
            <Field label="Start date">
              <Input type="date" value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} />
            </Field>
            <Field label="Target date">
              <Input type="date" value={form.targetDate} onChange={(e) => setForm({ ...form, targetDate: e.target.value })} />
            </Field>
            <LinkSelect label="Area" value={form.areaId} options={options?.areas} onChange={(v) => setForm({ ...form, areaId: v })} />
            <LinkSelect label="Goal" value={form.goalId} options={options?.goals} onChange={(v) => setForm({ ...form, goalId: v })} />
          </div>
        </div>
      </Dialog>
    </>
  );
}

// ---------------- Area ----------------
export function EditAreaButton({
  area,
  iconOnly = false,
}: {
  area: { id: string; title: string; description: string | null; type: string; health: string };
  iconOnly?: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);

  const initial = () => ({
    title: area.title,
    description: area.description ?? "",
    type: area.type,
    health: area.health,
  });
  const [form, setForm] = useState(initial);
  const archive = useArchiveFlow(start, "/areas", () => setOpen(false), run);

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await updateAreaAction(area.id, {
        title: form.title,
        description: form.description,
        type: form.type,
        health: form.health,
      });
      setOpen(false);
      router.refresh();
    }));
  };

  return (
    <>
      <EditTrigger
        iconOnly={iconOnly}
        className={iconOnly ? CARD_EDIT_TRIGGER : undefined}
        onClick={() => { setForm(initial()); setOpen(true); }}
      />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Edit area"
        error={error}
        footer={
          <>
            <DeleteFooterButton
              label="Delete"
              pending={pending}
              onDelete={() =>
                archive(
                  form.title,
                  form.type === "resource" ? "resource domain" : "area",
                  () => archiveAreaAction(area.id),
                )
              }
            />
            <SaveFooter pending={pending} disabled={!form.title.trim()} onCancel={() => setOpen(false)} onSave={submit} />
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <Select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {AREA_TYPES.map((t) => (
                  <option key={t} value={t}>{t === "area" ? "Area (responsibility)" : "Resource (topic)"}</option>
                ))}
              </Select>
            </Field>
            {form.type === "area" && (
              <Field label="Health">
                <Select value={form.health} onChange={(e) => setForm({ ...form, health: e.target.value })}>
                  {(Object.keys(AREA_HEALTH_META) as AreaHealth[]).map((h) => (
                    <option key={h} value={h}>{AREA_HEALTH_META[h].label}</option>
                  ))}
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
export function EditGoalButton({
  goal,
  iconOnly = false,
}: {
  iconOnly?: boolean;
  goal: {
    id: string;
    title: string;
    description: string | null;
    status: string;
    year: number | null;
    quarter: number | null;
    targetDate: Date | string | null;
    areaId: string | null;
  };
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const options = usePickerOptions(open);

  const initial = () => ({
    title: goal.title,
    description: goal.description ?? "",
    status: goal.status,
    year: goal.year ? String(goal.year) : "",
    quarter: goal.quarter ? String(goal.quarter) : "",
    targetDate: toDateInput(goal.targetDate),
    areaId: goal.areaId ?? "",
  });
  const [form, setForm] = useState(initial);
  const archive = useArchiveFlow(start, "/goals", () => setOpen(false), run);

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await updateGoalAction(goal.id, {
        title: form.title,
        description: form.description,
        status: form.status,
        year: form.year ? Number(form.year) : null,
        quarter: form.quarter ? Number(form.quarter) : null,
        targetDate: parseDateInput(form.targetDate),
        areaId: form.areaId || null,
      });
      setOpen(false);
      router.refresh();
    }));
  };

  return (
    <>
      <EditTrigger
        iconOnly={iconOnly}
        className={iconOnly ? CARD_EDIT_TRIGGER : undefined}
        onClick={() => { setForm(initial()); setOpen(true); }}
      />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Edit goal"
        error={error}
        footer={
          <>
            <DeleteFooterButton
              label="Delete"
              pending={pending}
              onDelete={() => archive(form.title, "goal", () => archiveGoalAction(goal.id))}
            />
            <SaveFooter pending={pending} disabled={!form.title.trim()} onCancel={() => setOpen(false)} onSave={submit} />
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
          <div className="grid grid-cols-2 gap-3">
            <Field label="Status">
              <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                {GOAL_STATUSES.map((s) => <option key={s} value={s}>{GOAL_STATUS_META[s].label}</option>)}
              </Select>
            </Field>
            <Field label="Target date">
              <Input type="date" value={form.targetDate} onChange={(e) => setForm({ ...form, targetDate: e.target.value })} />
            </Field>
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
            <LinkSelect label="Area" value={form.areaId} options={options?.areas} onChange={(v) => setForm({ ...form, areaId: v })} />
          </div>
        </div>
      </Dialog>
    </>
  );
}

// ---------------- Resource ----------------
export function EditResourceButton({
  resource,
  iconOnly = false,
}: {
  iconOnly?: boolean;
  resource: {
    id: string;
    title: string;
    url: string | null;
    type: string;
    status: string;
    summary: string | null;
    projectId: string | null;
    areaId: string | null;
  };
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const { error, run } = useFormActionError(open);
  const options = usePickerOptions(open);

  const initial = () => ({
    title: resource.title,
    url: resource.url ?? "",
    type: resource.type,
    status: resource.status,
    summary: resource.summary ?? "",
    projectId: resource.projectId ?? "",
    areaId: resource.areaId ?? "",
  });
  const [form, setForm] = useState(initial);
  const archive = useArchiveFlow(start, "/resources", () => setOpen(false), run);

  const submit = () => {
    if (!form.title.trim()) return;
    start(() => run(async () => {
      await updateResourceAction(resource.id, {
        title: form.title,
        url: form.url || null,
        type: form.type,
        status: form.status,
        summary: form.summary,
        projectId: form.projectId || null,
        areaId: form.areaId || null,
      });
      setOpen(false);
      router.refresh();
    }));
  };

  return (
    <>
      <EditTrigger
        iconOnly={iconOnly}
        className={iconOnly ? CARD_EDIT_TRIGGER : undefined}
        onClick={() => { setForm(initial()); setOpen(true); }}
      />
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Edit resource"
        error={error}
        footer={
          <>
            <DeleteFooterButton
              label="Delete"
              pending={pending}
              onDelete={() =>
                archive(form.title, "resource", () => archiveResourceAction(resource.id))
              }
            />
            <SaveFooter pending={pending} disabled={!form.title.trim()} onCancel={() => setOpen(false)} onSave={submit} />
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
            <Textarea rows={3} maxLength={20_000} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <Select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {RESOURCE_TYPES.map((t) => <option key={t} value={t}>{RESOURCE_TYPE_META[t].label}</option>)}
              </Select>
            </Field>
            <Field label="Status">
              <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                {RESOURCE_STATUSES.map((s) => <option key={s} value={s}>{RESOURCE_STATUS_META[s].label}</option>)}
              </Select>
            </Field>
            <LinkSelect label="Project" value={form.projectId} options={options?.projects} onChange={(v) => setForm({ ...form, projectId: v })} />
            <LinkSelect label="Area" value={form.areaId} options={options?.areas} onChange={(v) => setForm({ ...form, areaId: v })} />
          </div>
        </div>
      </Dialog>
    </>
  );
}
