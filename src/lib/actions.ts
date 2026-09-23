"use server";

import { revalidatePath } from "next/cache";
import * as capture from "@/lib/services/capture";
import * as tasks from "@/lib/services/tasks";
import * as projects from "@/lib/services/projects";
import * as notes from "@/lib/services/notes";
import * as resources from "@/lib/services/resources";
import * as areas from "@/lib/services/areas";
import * as goals from "@/lib/services/goals";
import * as reviews from "@/lib/services/reviews";
import * as automation from "@/lib/services/automation";
import * as g2Agent from "@/lib/services/g2-agent";
import * as research from "@/lib/services/research";
import * as labNotebook from "@/lib/services/labNotebook";
import { setAgentModel } from "@/lib/services/agent-models";
import * as taskExtract from "@/lib/services/taskExtract";
import * as dayPlan from "@/lib/services/dayPlan";
import * as timeLog from "@/lib/services/timeLog";
import {
  captureInputSchema,
  agentModelSchema,
  g2AgentRunSchema,
  labRunSchema,
  projectStatusSchema,
  notebookEntryCreateSchema,
  notebookEntryUpdateSchema,
  noteInputSchema,
  projectInputSchema,
  proposedTasksSchema,
  researchBibliographyItemIdSchema,
  researchBibliographyReclassifySchema,
  researchDigestSaveSchema,
  researchReviewRequestSchema,
  resourceInputSchema,
  reviewInputSchema,
  taskCalendarMoveSchema,
  taskInputSchema,
  taskPlacementSchema,
  timeEntryInputSchema,
} from "@/lib/validators";
import type { ReviewType } from "@/lib/types";

/**
 * Server actions = the web UI's write path. Each one validates with the same
 * zod schemas the REST API uses, calls the framework-free service, then
 * revalidates affected routes. Business logic lives in services, never here.
 */

function revalidateAll() {
  for (const p of [
    "/", "/today", "/inbox", "/tasks", "/projects", "/areas",
    "/notes", "/resources", "/goals", "/reviews", "/archive",
  ]) {
    revalidatePath(p);
  }
}

// ---------- Capture ----------
export async function captureAction(input: unknown) {
  const data = captureInputSchema.parse({ ...(input as object), source: "web" });
  const result = await capture.createInboxItem(data);
  revalidateAll();
  return result;
}

export async function processInboxAction(
  id: string,
  into: "task" | "note" | "resource",
  overrides?: { title?: string; projectId?: string | null; areaId?: string | null }
) {
  const result = await capture.processInboxItem(id, into, overrides);
  revalidateAll();
  return result;
}

export async function archiveInboxAction(id: string) {
  await capture.archiveInboxItem(id);
  revalidatePath("/inbox");
}

export async function retryInboxAutomationAction(id: string) {
  await automation.retryCaptureAutomation(id);
  revalidatePath("/inbox");
  revalidatePath("/today");
}

export async function correctAppliedCaptureAction(
  inboxItemId: string,
  correction: automation.CaptureCorrection,
) {
  const result = await automation.correctAppliedCapture(inboxItemId, correction);
  revalidateAll();
  return result;
}

export async function runVaultAutomationAction() {
  automation.startVaultAutomationCycle();
  revalidatePath("/today");
  revalidatePath("/inbox");
  revalidatePath("/ops");
  return { started: true };
}

export async function launchG2AgentAction(input: unknown) {
  return g2Agent.startG2AgentRun(g2AgentRunSchema.parse(input));
}

export async function getG2AgentRunAction(id: string) {
  return g2Agent.getG2AgentRun(id);
}

export async function getRecentG2AgentRunsAction() {
  return g2Agent.listRecentG2AgentRuns(10);
}

export async function dismissAllG2AgentRunsAction() {
  const cleared = await g2Agent.dismissFinishedG2AgentRuns();
  revalidatePath("/ops");
  revalidatePath("/teams");
  return { cleared, runs: await g2Agent.listRecentG2AgentRuns(10) };
}

export async function dismissG2AgentRunAction(id: string) {
  await g2Agent.dismissG2AgentRun(id);
  revalidatePath("/ops");
  revalidatePath("/teams");
  return g2Agent.listRecentG2AgentRuns(10);
}

export async function cancelG2AgentRunAction(id: string) {
  const result = await g2Agent.cancelG2AgentRun(id);
  revalidatePath("/ops");
  return result;
}

export async function requestPaperReviewAction(input: unknown) {
  const result = await research.requestPaperReview(
    researchReviewRequestSchema.parse(input),
  );
  revalidatePath("/today");
  revalidatePath("/research");
  revalidatePath("/teams");
  return result;
}

export async function getResearchReviewStatusAction(jobId: string) {
  return research.getResearchReviewStatus(jobId);
}

export async function saveDigestToLibraryAction(input: unknown) {
  const data = researchDigestSaveSchema.parse(input);
  const result = await research.saveDigestToLibrary(
    data.digestPath,
    data.targetType && data.targetId
      ? { type: data.targetType, id: data.targetId }
      : undefined,
  );
  revalidatePath("/today");
  revalidatePath("/research");
  return result;
}

export async function archiveBibliographyItemAction(itemId: unknown) {
  const result = await research.archiveBibliographyItem(
    researchBibliographyItemIdSchema.parse(itemId),
  );
  revalidatePath("/research");
  return result;
}

export async function reclassifyBibliographyItemAction(input: unknown) {
  const data = researchBibliographyReclassifySchema.parse(input);
  const result = await research.reclassifyBibliographyItem(
    data.itemId,
    data.targetType && data.targetId
      ? { type: data.targetType, id: data.targetId }
      : undefined,
  );
  revalidatePath("/research");
  return result;
}

// ---------- Tasks ----------
export async function createTaskAction(input: unknown) {
  const data = taskInputSchema.parse(input);
  const task = await tasks.createTask(data);
  revalidateAll();
  return task;
}

export async function updateTaskAction(id: string, input: unknown) {
  const data = taskInputSchema.partial().parse(input);
  const task = await tasks.updateTask(id, data);
  revalidateAll();
  return task;
}

export async function toggleTaskAction(id: string) {
  const task = await tasks.toggleTaskComplete(id);
  revalidateAll();
  return task;
}

export async function setHighlightAction(id: string, isHighlight: boolean) {
  await tasks.setTaskHighlight(id, isHighlight);
  revalidatePath("/today");
  revalidatePath("/tasks");
}

export async function rescheduleTaskAction(id: string, iso: string | null) {
  await tasks.rescheduleTask(id, iso ? new Date(iso) : null);
  revalidateAll();
}

export async function moveTaskToCalendarDateAction(id: string, targetDate: unknown) {
  const data = taskCalendarMoveSchema.parse({ targetDate });
  const task = await tasks.moveTaskToCalendarDate(id, data.targetDate);
  revalidateAll();
  return task;
}

/**
 * Takes no argument on purpose: "today" is resolved on the server, so the
 * browser cannot name the day the sweep lands on.
 */
export async function pullOverdueTasksToTodayAction() {
  const count = await tasks.pullOverdueTasksToToday();
  revalidateAll();
  return count;
}

export async function clearCompletedTasksAction() {
  const count = await tasks.clearCompletedTasks();
  revalidateAll();
  return count;
}

export async function deleteTaskAction(id: string) {
  await tasks.deleteTask(id);
  revalidateAll();
}

/**
 * Rebuild today's suggested schedule from the live task table. Takes no
 * argument on purpose, like pullOverdueTasksToTodayAction: "today" and "now"
 * are resolved on the server. Writes only the plan file under
 * `.claude/data/state/`; no task is changed.
 */
export async function regenerateDayPlanAction() {
  const plan = await dayPlan.regenerateDayPlan();
  revalidatePath("/today");
  return { generatedAt: plan.generatedAt, placed: plan.items.filter((i) => i.kind === "task").length };
}

/**
 * A task dropped onto the Plan column. Gives the task that time today (the
 * week strip's own reschedule write) and re-packs the stored plan around it.
 */
export async function placeTaskInPlanAction(input: unknown) {
  const data = taskPlacementSchema.parse(input);
  const plan = await dayPlan.placeTaskInPlan(data.taskId, data.startAt);
  revalidateAll();
  return { placed: plan.items.filter((i) => i.kind === "task").length };
}

// ---------- Actual side of the Plan & actual board ----------
export async function createTimeEntryAction(input: unknown) {
  const data = timeEntryInputSchema.parse(input);
  const entry = await timeLog.createTimeEntry(data);
  revalidatePath("/today");
  return entry;
}

export async function updateTimeEntryAction(id: string, input: unknown) {
  const data = timeEntryInputSchema.parse(input);
  const entry = await timeLog.updateTimeEntry(id, data);
  revalidatePath("/today");
  return entry;
}

/** Archives, never deletes: the row stays for the record of the day. */
export async function archiveTimeEntryAction(id: string) {
  await timeLog.archiveTimeEntry(id);
  revalidatePath("/today");
}

/**
 * Tasks for the week containing `anchorIso`, so the Today week strip can page
 * backwards and forwards without navigating away from the page. The current
 * week still arrives with the server render; this only fills the ones she
 * scrolls to.
 *
 * Shaped down to what a calendar cell renders — a full task row carries tags
 * and descriptions the strip never shows, and this runs on every arrow press.
 */
export async function getWeekTasksAction(anchorIso: string) {
  const anchor = new Date(anchorIso);
  if (Number.isNaN(anchor.getTime())) throw new Error("Invalid week anchor");
  const week = await tasks.getWeekTasks(anchor);
  return week.map((task) => ({
    id: task.id,
    title: task.title,
    status: task.status,
    priority: task.priority,
    context: task.context,
    dueDate: task.dueDate,
    scheduledDate: task.scheduledDate,
    // isHighlight and the link titles are carried because the day panel below
    // the calendar renders full task rows, and the editor's highlight toggle
    // has to know its current state in a paged-to week too.
    isHighlight: task.isHighlight,
    project: task.project ? { id: task.project.id, title: task.project.title } : null,
    area: task.area ? { id: task.area.id, title: task.area.title } : null,
  }));
}

// ---------- Projects ----------
export async function createProjectAction(input: unknown) {
  const data = projectInputSchema.parse(input);
  const project = await projects.createProject(data);
  revalidateAll();
  return project;
}

export async function updateProjectAction(id: string, input: unknown) {
  const data = projectInputSchema.partial().parse(input);
  const project = await projects.updateProject(id, data);
  revalidateAll();
  revalidatePath(`/projects/${id}`);
  return project;
}

export async function archiveProjectAction(id: string) {
  await projects.archiveProject(id);
  revalidateAll();
  revalidatePath(`/projects/${id}`);
}

export async function setProjectStatusAction(id: string, status: string) {
  await projects.setProjectStatus(id, projectStatusSchema.parse(status));
  revalidateAll();
  revalidatePath(`/projects/${id}`);
  // A project leaving or entering Active moves its notebook entries between
  // the notebook and the archive view.
  revalidatePath("/research/notebook");
  revalidatePath("/research/notebook/archive");
}

export async function setNextActionAction(projectId: string, taskId: string | null) {
  await projects.setNextAction(projectId, taskId);
  revalidatePath(`/projects/${projectId}`);
  revalidatePath("/today");
}

// ---------- Notes ----------
export async function createNoteAction(input: unknown) {
  const data = noteInputSchema.parse(input);
  const note = await notes.createNote(data);
  revalidateAll();
  return note;
}

export async function updateNoteAction(id: string, input: unknown) {
  const data = noteInputSchema.partial().parse(input);
  const note = await notes.updateNote(id, data);
  revalidateAll();
  revalidatePath(`/notes/${id}`);
  return note;
}

export async function togglePinNoteAction(id: string) {
  await notes.togglePinNote(id);
  revalidatePath("/notes");
  revalidatePath(`/notes/${id}`);
  revalidatePath("/");
}

export async function deleteNoteAction(id: string) {
  await notes.deleteNote(id);
  revalidateAll();
}

export async function archiveNoteAction(id: string) {
  await notes.archiveNote(id);
  revalidateAll();
}

export async function saveDailyNoteAction(content: string, iso?: string) {
  await notes.upsertDailyNote(content, iso ? new Date(iso) : new Date());
  revalidatePath("/today");
}

// ---------- Resources ----------
export async function createResourceAction(input: unknown) {
  const data = resourceInputSchema.parse(input);
  const resource = await resources.createResource(data);
  revalidateAll();
  return resource;
}

export async function updateResourceAction(id: string, input: unknown) {
  const data = resourceInputSchema.partial().parse(input);
  const resource = await resources.updateResource(id, data);
  revalidateAll();
  revalidatePath(`/resources/${id}`);
  return resource;
}

export async function archiveResourceAction(id: string) {
  await resources.archiveResource(id);
  revalidateAll();
  revalidatePath(`/resources/${id}`);
}

// ---------- Areas ----------
export async function createAreaAction(input: {
  title: string;
  description?: string;
  type?: string;
  icon?: string;
}) {
  const area = await areas.createArea(input);
  revalidateAll();
  return area;
}

export async function updateAreaAction(
  id: string,
  input: Partial<{ title: string; description: string; type: string; health: string; pinned: boolean }>
) {
  const area = await areas.updateArea(id, input);
  revalidateAll();
  revalidatePath(`/areas/${id}`);
  return area;
}

export async function archiveAreaAction(id: string) {
  await areas.archiveArea(id);
  revalidateAll();
  revalidatePath(`/areas/${id}`);
}

// ---------- Goals ----------
export async function createGoalAction(input: {
  title: string;
  description?: string;
  year?: number;
  quarter?: number;
  areaId?: string | null;
}) {
  const goal = await goals.createGoal(input);
  revalidateAll();
  return goal;
}

export async function updateGoalAction(
  id: string,
  input: Partial<{
    title: string;
    description: string;
    status: string;
    year: number | null;
    quarter: number | null;
    targetDate: Date | null;
    areaId: string | null;
  }>
) {
  const goal = await goals.updateGoal(id, input);
  revalidateAll();
  revalidatePath(`/goals/${id}`);
  return goal;
}

export async function archiveGoalAction(id: string) {
  await goals.archiveGoal(id);
  revalidateAll();
  revalidatePath(`/goals/${id}`);
}

// ---------- Picker options ----------
/**
 * Lightweight option lists for edit dialogs, so any client component can
 * offer project/area/goal pickers without every page threading them through.
 */
export async function getPickerOptionsAction() {
  const [projectList, areaList, goalList] = await Promise.all([
    projects.listProjects(),
    areas.listAreas(),
    goals.listGoals(),
  ]);
  const opt = (x: { id: string; title: string }) => ({ id: x.id, title: x.title });
  return {
    projects: projectList.map((project) => ({
      id: project.id,
      title: project.title,
      areaId: project.areaId,
    })),
    areas: areaList.map(opt),
    goals: goalList.map(opt),
  };
}

// ---------- Text -> tasks ----------
/**
 * Propose tasks from free text (the daily note, or a review's priorities).
 * Read-only: the preview dialog decides what actually gets created.
 */
export async function proposeTasksAction(text: string, opts?: { sections?: boolean }) {
  return taskExtract.buildTaskCandidates(String(text ?? ""), {
    sections: opts?.sections !== false,
  });
}

/**
 * Create the candidates they kept. Each is validated by the same task schema
 * as every other write path, so nothing the parser produced is trusted.
 */
export async function createProposedTasksAction(input: unknown) {
  const rows = proposedTasksSchema.parse(input);
  const created = [];
  for (const row of rows) {
    created.push(await tasks.createTask(row));
  }
  revalidateAll();
  return { created: created.length };
}

// ---------- Reviews ----------
export async function saveReviewAction(input: unknown) {
  const data = reviewInputSchema.parse(input);
  const review = await reviews.upsertReview(data);
  revalidatePath("/reviews");
  revalidatePath("/today");
  return review;
}

export async function deleteReviewAction(id: string) {
  await reviews.deleteReview(id);
  revalidatePath("/reviews");
}

export type { ReviewType };

// ---------- Agent model picker (/teams) ----------

export async function setAgentModelAction(input: unknown) {
  const policy = await setAgentModel(agentModelSchema.parse(input));
  revalidatePath("/teams");
  return policy;
}

// ---------- Lab notebook (Research desk) ----------
function revalidateNotebook(projectCode?: string, name?: string) {
  revalidatePath("/research/notebook");
  if (projectCode && name) revalidatePath(`/research/notebook/${projectCode}/${name}`);
  revalidatePath("/notes");
}

export async function launchLabRunAction(input: unknown) {
  const data = labRunSchema.parse(input);
  const run = await labNotebook.startLabRun(data);
  revalidateNotebook();
  if (data.newProject) revalidateAll();
  return run;
}

export async function getLabRunsAction() {
  return labNotebook.listLabRuns(10);
}

export async function cancelLabRunAction(id: string) {
  const run = await labNotebook.cancelLabRun(String(id));
  revalidateNotebook();
  return run;
}

export async function dismissLabRunAction(id: string) {
  await labNotebook.dismissLabRun(String(id));
  revalidateNotebook();
}

export async function nextExperimentIdAction(projectCode: string) {
  return labNotebook.nextExperimentId(String(projectCode));
}

export async function createNotebookEntryAction(input: unknown) {
  const data = notebookEntryCreateSchema.parse(input);
  const saved = await labNotebook.saveNotebookEntry(data);
  revalidateNotebook(saved.projectCode, saved.title);
  if (data.newProject) revalidateAll();
  return saved;
}

export async function updateNotebookEntryAction(input: unknown) {
  const { projectCode, entryName, ...rest } = notebookEntryUpdateSchema.parse(input);
  const saved = await labNotebook.updateNotebookEntry(projectCode, entryName, rest);
  revalidateNotebook(projectCode, saved.title);
  return saved;
}

/**
 * The entry's unchecked next steps as task candidates, filed under the
 * matching planner project. Read-only: the shared preview dialog decides.
 */
export async function proposeNotebookTasksAction(projectCode: string, entryName: string) {
  const entry = await labNotebook.getNotebookEntry(String(projectCode), String(entryName));
  if (!entry) throw new Error("Notebook entry not found.");
  const proposal = await taskExtract.buildTaskCandidates(entry.nextSteps.join("\n"), { sections: false });
  const project = await labNotebook.prismaProjectFor(entry.projectCode);
  return {
    ...proposal,
    candidates: proposal.candidates.map((c) => ({
      ...c,
      projectId: c.projectId ?? project?.id ?? null,
      description: c.description ?? `From lab notebook ${entry.name}`,
    })),
  };
}
