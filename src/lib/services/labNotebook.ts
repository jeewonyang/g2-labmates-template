/**
 * Lab notebook + LabSerf launcher (Research desk, 2026-09-21).
 *
 * Read side is filesystem-only and framework-free, like `hr.ts`:
 *  - entries are markdown files under
 *    `VAULT/Research-Private/10_Projects/<project>/04_Notebook/`, written only
 *    by `.claude/scripts/lab_notebook.py`. This file parses them and never
 *    writes them; every write spawns that CLI, so the format has one owner;
 *  - runs are JSON files under `.claude/data/state/lab-runs/`, written by
 *    `lab_run.py` (the `g2-agent.ts` shape: the browser supplies an
 *    idempotency UUID, the assay, the project, paths, options and
 *    instructions - never a command, a model, or an output location).
 *
 * Reports, never asserts: `getLabEnvironment()` says whether LabSerf and its
 * interpreter exist on *this* machine instead of letting a launch spawn and
 * crash.
 */

import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync, promises as fs } from "node:fs";
import path from "node:path";
import { db } from "@/lib/db";

const REPO = process.cwd();
const PYTHON =
  process.env.SECONDBRAIN_PYTHON || "python";
const NOTEBOOK_SCRIPT = path.join(REPO, ".claude", "scripts", "lab_notebook.py");
const RUN_SCRIPT = path.join(REPO, ".claude", "scripts", "lab_run.py");
const PROJECTS_ROOT = path.join(REPO, "VAULT", "Research-Private", "10_Projects");
const RUNS_DIR = path.join(REPO, ".claude", "data", "state", "lab-runs");
/**
 * The LabSerf bench: its agents, skills and negative-result ledger. Ships in
 * this repo under `labserf/`; LABSERF_ROOT points at another checkout.
 * Same resolution as `lab_run.LABSERF` (two copies, asserted by
 * tests/test_lab_notebook.py).
 */
export const LABSERF_ROOT = process.env.LABSERF_ROOT || path.join(REPO, "labserf");
const LABSERF = LABSERF_ROOT;
const NOTEBOOK_DIR = "04_Notebook";
/** Same place as `lab_notebook.ARCHIVE_ROOT`. */
const ARCHIVE_ROOT = path.join(REPO, "VAULT", "Research-Private", "90_Archive", "Lab Notebook");
/** Same default as `lab_run.labserf_python()`: LABSERF_PYTHON, else the agent Python. */
const LABSERF_PYTHON = process.env.LABSERF_PYTHON || PYTHON;

// Two copies of one fact, asserted equal by tests/test_lab_notebook.py.
// The source of truth is lab_notebook.PROJECT_FOLDER / TITLE / SECTIONS.
export const PROJECT_FOLDER_PATTERN = "^(?:\\d{2}_)?([A-Za-z][A-Za-z0-9]*)$";
export const ENTRY_TITLE_PATTERN =
  "^([A-Za-z0-9][A-Za-z0-9-]{0,23})_([A-Za-z0-9]+)_(\\d{4}-\\d{2}-\\d{2})$";
export const NOTEBOOK_SECTIONS = [
  "Introduction",
  "Objective",
  "Materials & Methods",
  "Result",
  "Conclusion",
] as const;
const PROJECT_FOLDER = new RegExp(PROJECT_FOLDER_PATTERN);
const ENTRY_TITLE = new RegExp(ENTRY_TITLE_PATTERN);

export const LAB_ASSAYS = ["flow", "ultrasound", "primer-design"] as const;
export type LabAssay = (typeof LAB_ASSAYS)[number];
// Same list as lab_notebook.ASSAYS (tests/test_lab_notebook.py asserts it).
export const ENTRY_ASSAYS = ["flow", "ultrasound", "primer-design", "bench", "computational", "other"] as const;
export const ENTRY_OUTCOMES = [
  "positive",
  "negative",
  "mixed",
  "inconclusive",
  "technical-failure",
  "pending",
] as const;

export { ASSAY_LABEL } from "@/lib/lab-notebook-labels";

export type LabProject = {
  code: string;
  folder: string;
  /** Every entry of the project, wherever its file sits. */
  entryCount: number;
  latest: string | null;
  /** The matched planner project and its status; null when none matches. */
  planner: { id: string; title: string; status: string } | null;
  /** Planner status is Active - the only projects the notebook works on. */
  active: boolean;
};

export type NotebookEntrySummary = {
  name: string; // filename stem == title
  projectCode: string;
  experimentId: string;
  date: string;
  label: string;
  summary: string;
  assay: string;
  outcome: string;
  status: string;
  inputPath: string;
  resultPath: string;
  updated: string;
  /** The file sits under 90_Archive/Lab Notebook/ (older entries); visibility follows the project's status, not this. */
  archived: boolean;
  /** Where a past entry came from ("onenote"), empty for G2-made entries. */
  source: string;
  /** Which path filed it: "skill", "auto" (SessionEnd auto-log), "lab-run"; empty before 2026-09-22. */
  loggedBy: string;
};

export type NotebookEntry = NotebookEntrySummary & {
  fm: Record<string, string>;
  body: string;
  nextSteps: string[];
  relPath: string;
};

// ------------------------------------------------------------------ parsing

export function parseFrontmatter(text: string): { fm: Record<string, string>; body: string } {
  const normalized = text.replace(/\r\n/g, "\n");
  if (!normalized.startsWith("---\n")) return { fm: {}, body: normalized };
  const end = normalized.indexOf("\n---\n", 4);
  if (end < 0) return { fm: {}, body: normalized };
  const fm: Record<string, string> = {};
  for (const line of normalized.slice(4, end).split("\n")) {
    const at = line.indexOf(":");
    if (at < 0) continue;
    let value = line.slice(at + 1).trim();
    if (value.startsWith('"')) {
      try {
        value = JSON.parse(value);
      } catch {
        // keep the raw text; a hand edit in Obsidian may not be JSON-quoted
      }
    }
    fm[line.slice(0, at).trim()] = value;
  }
  return { fm, body: normalized.slice(end + 5) };
}

export function nextStepsOf(body: string): string[] {
  const conclusion = body.split(/^## Conclusion\s*$/m)[1] ?? "";
  const block = conclusion.split(/^### Next steps\s*$/m)[1] ?? "";
  return block
    .split("\n")
    .map((line) => line.match(/^\s*-\s*\[ \]\s+(.+)$/)?.[1]?.trim())
    .filter((line): line is string => Boolean(line));
}

function summaryOf(stem: string, projectCode: string, text: string): NotebookEntrySummary {
  const { fm, body } = parseFrontmatter(text);
  const title = stem.match(ENTRY_TITLE);
  const quote = body.match(/^>\s*(.+)$/m)?.[1] ?? "";
  return {
    name: stem,
    projectCode,
    experimentId: fm.experiment_id || title?.[1] || stem,
    date: fm.date || title?.[3] || "",
    label: fm.name || "",
    summary: quote,
    assay: fm.assay || "other",
    outcome: fm.outcome || "pending",
    status: fm.status || "draft",
    inputPath: fm.input_path || "",
    resultPath: fm.result_path || "",
    updated: fm.updated || "",
    archived: false,
    source: fm.source || "",
    loggedBy: fm.logged_by || "",
  };
}

// ------------------------------------------------------------------ reading

async function projectFolders(): Promise<Array<{ code: string; folder: string }>> {
  let names: string[];
  try {
    names = await fs.readdir(PROJECTS_ROOT);
  } catch {
    return [];
  }
  const out = [];
  for (const folder of names.sort()) {
    const match = folder.match(PROJECT_FOLDER);
    if (!match) continue;
    const stat = await fs.stat(path.join(PROJECTS_ROOT, folder)).catch(() => null);
    if (stat?.isDirectory()) out.push({ code: match[1], folder });
  }
  return out;
}

async function folderFor(code: string): Promise<string | null> {
  const want = code.trim().toLowerCase();
  const hit = (await projectFolders()).find((p) => p.code.toLowerCase() === want);
  return hit ? path.join(PROJECTS_ROOT, hit.folder) : null;
}

async function entriesIn(
  folder: string,
  code: string,
  sub: string = NOTEBOOK_DIR,
): Promise<NotebookEntrySummary[]> {
  const dir = sub ? path.join(folder, sub) : folder;
  let names: string[];
  try {
    names = await fs.readdir(dir);
  } catch {
    return [];
  }
  const rows = await Promise.all(
    names
      .filter((n) => n.endsWith(".md") && ENTRY_TITLE.test(n.slice(0, -3)))
      .map(async (n) => {
        const text = await fs.readFile(path.join(dir, n), "utf8").catch(() => "");
        return text ? summaryOf(n.slice(0, -3), code, text) : null;
      }),
  );
  return rows.filter((r): r is NotebookEntrySummary => Boolean(r));
}

function newestFirst(a: NotebookEntrySummary, b: NotebookEntrySummary): number {
  return b.date.localeCompare(a.date) || b.experimentId.localeCompare(a.experimentId, undefined, { numeric: true });
}

type PlannerProject = { id: string; title: string; status: string };

/**
 * The planner project a notebook code names, archived ones included (their
 * entries belong in the archive view, not nowhere). An exact title match wins,
 * else a unique title containing the code; a live project outranks an
 * archived one of the same name. Status is the planner's, and the planner is
 * the only place it is stored - the notebook never keeps its own copy.
 */
function matchPlanner(
  code: string,
  rows: Array<PlannerProject & { archivedAt: Date | null }>,
): PlannerProject | null {
  const want = code.toLowerCase();
  const pick = (hits: typeof rows): PlannerProject | null => {
    const live = hits.filter((r) => !r.archivedAt);
    const chosen =
      live.length === 1 ? live[0] : live.length === 0 && hits.length === 1 ? hits[0] : null;
    return chosen
      ? { id: chosen.id, title: chosen.title, status: chosen.archivedAt ? "archived" : chosen.status }
      : null;
  };
  return (
    pick(rows.filter((r) => r.title.trim().toLowerCase() === want)) ??
    pick(rows.filter((r) => r.title.toLowerCase().includes(want)))
  );
}

async function plannerRows() {
  return db.project.findMany({ select: { id: true, title: true, status: true, archivedAt: true } });
}

async function archivedEntriesFor(code: string): Promise<NotebookEntrySummary[]> {
  const rows = await entriesIn(path.join(ARCHIVE_ROOT, code), code, "");
  return rows.map((r) => ({ ...r, archived: true }));
}

export async function listLabProjects(): Promise<LabProject[]> {
  const [folders, rows] = await Promise.all([projectFolders(), plannerRows()]);
  return Promise.all(
    folders.map(async ({ code, folder }) => {
      const entries = (await entriesIn(path.join(PROJECTS_ROOT, folder), code)).sort(newestFirst);
      const archived = await archivedEntriesFor(code);
      const planner = matchPlanner(code, rows);
      return {
        code,
        folder,
        entryCount: entries.length + archived.length,
        latest: entries[0]?.date ?? null,
        planner,
        active: planner?.status === "active",
      };
    }),
  );
}

/**
 * Notebook entries by their project's status - the only thing that decides
 * where an entry shows (the owner, 2026-09-21: "all the notes for active
 * projects show up in the entries, even the OneNotes; just finished project
 * notebooks go to Archive"):
 *  - "active": every entry of a project whose planner status is Active,
 *    made in G2 or imported from OneNote;
 *  - "archive": every entry of a project that is not Active - Done in the
 *    first place, and also Paused or not in the planner, so nothing a
 *    project holds is ever out of sight.
 * Where the file sits does not matter; a project set back to Active brings
 * its whole notebook back.
 */
export async function listNotebookEntries(
  projectCode?: string | null,
  scope: "active" | "archive" = "active",
): Promise<NotebookEntrySummary[]> {
  const projects = await listLabProjects();
  const want = projectCode?.trim().toLowerCase();
  const chosen = (want ? projects.filter((p) => p.code.toLowerCase() === want) : projects).filter(
    (p) => (scope === "active" ? p.active : !p.active),
  );
  const all = await Promise.all(
    chosen.map(async (p) => [
      ...(await entriesIn(path.join(PROJECTS_ROOT, p.folder), p.code)),
      // Entries an earlier version filed under 90_Archive still belong to
      // their project and show with it.
      ...(await archivedEntriesFor(p.code)),
    ]),
  );
  return all.flat().sort(newestFirst);
}

/**
 * One entry, from its project notebook or from the archive. The name must be
 * a title (no separators), and the file must sit directly in one of the two
 * folders - the second lock against traversal.
 */
export async function getNotebookEntry(projectCode: string, name: string): Promise<NotebookEntry | null> {
  if (!ENTRY_TITLE.test(name)) return null;
  const folder = await folderFor(projectCode);
  if (!folder) return null;
  const code = path.basename(folder).match(PROJECT_FOLDER)?.[1] ?? projectCode;
  const candidates: Array<[string, boolean]> = [
    [path.join(folder, NOTEBOOK_DIR), false],
    [path.join(ARCHIVE_ROOT, code), true],
  ];
  for (const [dir, archived] of candidates) {
    const file = path.join(dir, `${name}.md`);
    if (path.dirname(file) !== dir) return null;
    let text: string;
    try {
      text = await fs.readFile(file, "utf8");
    } catch {
      continue;
    }
    const { fm, body } = parseFrontmatter(text);
    return {
      ...summaryOf(name, code, text),
      archived,
      fm,
      body,
      nextSteps: nextStepsOf(body),
      relPath: path.relative(REPO, file).split(path.sep).join("/"),
    };
  }
  return null;
}

/** The planner project a notebook code names (live ones only), when exactly one does. */
export async function prismaProjectFor(code: string): Promise<{ id: string; title: string } | null> {
  const planner = matchPlanner(code, await plannerRows());
  return planner && planner.status !== "archived" ? { id: planner.id, title: planner.title } : null;
}

/** Whether a notebook project is Active in the planner - launches and new entries require it. */
export async function isActiveLabProject(code: string): Promise<boolean> {
  const want = code.trim().toLowerCase();
  return (await listLabProjects()).some((p) => p.code.toLowerCase() === want && p.active);
}

/**
 * Start a project from the notebook: its Research-Private folder (through the
 * writer) and an Active planner project titled with the same code. Reuses an
 * existing project of that code rather than making a second one, and refuses
 * one that exists but is not Active - reviving a Done project is a status
 * change, not a new project.
 */
export async function createLabProject(rawCode: string): Promise<{ code: string; plannerId: string }> {
  const code = rawCode.trim();
  const folder = await runNotebookCli<{ code: string; created: boolean }>([
    "create-project", "--code", code,
  ]);
  const project = (await listLabProjects()).find((p) => p.code === folder.code);
  if (project?.planner) {
    if (!project.active) {
      throw new Error(
        `${project.code} already exists and is ${project.planner.status}. Set it back to Active instead of creating it again.`,
      );
    }
    return { code: project.code, plannerId: project.planner.id };
  }
  const planner = await db.project.create({
    data: { title: folder.code, status: "active" },
    select: { id: true },
  });
  return { code: folder.code, plannerId: planner.id };
}

// ------------------------------------------------------------------ writing

export type NotebookEntryInput = {
  projectCode: string;
  experimentId?: string;
  date?: string;
  name?: string;
  summary?: string;
  assay: string;
  outcome: string;
  status?: string;
  inputPath: string;
  resultPath: string;
  introduction?: string;
  objective?: string;
  materialsMethods?: string;
  result?: string;
  conclusion?: string;
  nextSteps?: string[];
};

function runNotebookCli<T>(args: string[], input?: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON, [NOTEBOOK_SCRIPT, ...args], {
      cwd: REPO,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, CLAUDE_INVOKED_BY: "lab-notebook", PYTHONUTF8: "1" },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (c: string) => (stdout += c));
    child.stderr.on("data", (c: string) => (stderr += c));
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("The notebook writer timed out."));
    }, 30_000);
    child.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      let parsed: (T & { error?: string }) | null = null;
      try {
        parsed = JSON.parse(stdout.trim());
      } catch {
        reject(new Error(stderr.trim() || "The notebook writer returned an unreadable response."));
        return;
      }
      if (!parsed || code !== 0 || parsed.error) {
        reject(new Error(parsed?.error || stderr.trim() || "The notebook writer failed."));
        return;
      }
      resolve(parsed);
    });
    child.stdin.end(input === undefined ? "" : JSON.stringify(input));
  });
}

export async function nextExperimentId(projectCode: string): Promise<string> {
  const out = await runNotebookCli<{ experimentId: string }>(["next-id", "--project", projectCode]);
  return out.experimentId;
}

export async function saveNotebookEntry(input: NotebookEntryInput & { newProject?: boolean }) {
  if (input.newProject) {
    input = { ...input, projectCode: (await createLabProject(input.projectCode)).code };
  }
  if (!(await isActiveLabProject(input.projectCode))) {
    throw new Error(`${input.projectCode} is not Active in the planner. New entries go to Active projects.`);
  }
  return runNotebookCli<{ path: string; title: string; replaced: boolean; projectCode: string }>(
    ["write"],
    {
      project_code: input.projectCode,
      experiment_id: input.experimentId || undefined,
      date: input.date || undefined,
      name: input.name,
      summary: input.summary,
      assay: input.assay,
      outcome: input.outcome,
      status: input.status || "draft",
      input_path: input.inputPath,
      result_path: input.resultPath,
      introduction: input.introduction,
      objective: input.objective,
      materials_methods: input.materialsMethods,
      result: input.result,
      conclusion: input.conclusion,
      next_steps: input.nextSteps ?? [],
    },
  );
}

/**
 * Editing an entry rewrites it through the same writer, carrying over what
 * the form does not show (run id, NR id) so a hand edit never drops the
 * provenance an agent run recorded. `keep_provenance` has the writer keep the
 * rest (source_* of an import, code_* of a computational entry) from the file
 * it replaces, so the key list lives only in lab_notebook.KEPT_ON_REWRITE.
 * The previous version goes to .history/.
 */
export async function updateNotebookEntry(
  projectCode: string,
  name: string,
  input: Omit<NotebookEntryInput, "projectCode" | "experimentId" | "date">,
) {
  const current = await getNotebookEntry(projectCode, name);
  if (!current) throw new Error("Notebook entry not found.");
  return runNotebookCli<{ path: string; title: string; projectCode: string }>(["write"], {
    project_code: current.projectCode,
    experiment_id: current.experimentId,
    date: current.date,
    run_id: current.fm.run_id,
    negative_result_id: current.fm.negative_result_id,
    keep_provenance: true,
    name: input.name,
    summary: input.summary,
    assay: input.assay,
    outcome: input.outcome,
    status: input.status || current.status,
    input_path: input.inputPath,
    result_path: input.resultPath,
    introduction: input.introduction,
    objective: input.objective,
    materials_methods: input.materialsMethods,
    result: input.result,
    conclusion: input.conclusion,
    next_steps: input.nextSteps ?? [],
  });
}

/** The editable text of each section, without the lines the writer owns. */
export function sectionsOf(body: string): Record<(typeof NOTEBOOK_SECTIONS)[number], string> {
  const out = {} as Record<(typeof NOTEBOOK_SECTIONS)[number], string>;
  const parts = body.split(/^## /m);
  for (const section of NOTEBOOK_SECTIONS) {
    const part = parts.find((p) => p.startsWith(`${section}\n`)) ?? "";
    let text = part.slice(section.length + 1);
    if (section === "Materials & Methods") {
      text = text.replace(/^\s*- \*\*Input data:\*\*.*\n- \*\*Result data:\*\*.*\n?/, "");
    }
    if (section === "Conclusion") text = text.split(/^### Next steps\s*$/m)[0];
    text = text.trim();
    out[section] = text === "_Not yet written._" ? "" : text;
  }
  return out;
}

// ------------------------------------------------------------------ runs

export type LabRunStatus = "queued" | "running" | "cancel_requested" | "cancelled" | "completed" | "failed";

export type LabRun = {
  id: string;
  assay: LabAssay;
  projectCode: string;
  mode: "agent" | "pipeline";
  inputPath: string;
  dnaPaths?: string[];
  instructions: string;
  name?: string;
  options?: LabRunOptions;
  status: LabRunStatus;
  phase?: "waiting" | "pipeline" | "agent" | "notebook" | "finished";
  createdAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  heartbeatAt?: string | null;
  experimentId?: string;
  notebookTitle?: string;
  resultPath?: string;
  pipelineCommand?: string;
  pipeline?: { ok: boolean; exitCode: number | null; log: string; seconds?: number };
  model?: string;
  notebook?: { path: string; title: string; projectCode: string } | null;
  error?: string;
  dismissedAt?: string | null;
};

export type LabRunOptions = {
  negativeControl?: string;
  highlight?: string;
  compare?: string[];
  reference?: string;
};

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const LIVE: LabRunStatus[] = ["queued", "running", "cancel_requested"];

function runPath(id: string): string {
  if (!RUN_ID.test(id)) throw new Error("Invalid lab run id.");
  return path.join(RUNS_DIR, `${id}.json`);
}

async function writeJsonAtomic(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${randomUUID()}.tmp`;
  await fs.writeFile(temp, JSON.stringify(value, null, 2), { encoding: "utf8", flag: "wx" });
  await fs.rename(temp, file);
}

export type LabEnvironment = {
  labserf: boolean;
  python: boolean;
  pythonPath: string;
  problems: string[];
};

export function getLabEnvironment(): LabEnvironment {
  const labserf = existsSync(path.join(LABSERF, ".claude", "skills"));
  // A bare command name ("python") is resolved from PATH at run time; only an
  // explicit path can be checked here.
  const python = path.isAbsolute(LABSERF_PYTHON) ? existsSync(LABSERF_PYTHON) : true;
  const problems: string[] = [];
  if (!labserf) problems.push(`LabSerf is not at ${LABSERF}; set LABSERF_ROOT.`);
  if (!python) problems.push(`LabSerf's Python (${LABSERF_PYTHON}) is not on this machine; set LABSERF_PYTHON.`);
  return { labserf, python, pythonPath: LABSERF_PYTHON, problems };
}

export async function startLabRun(input: {
  clientRequestId: string;
  assay: LabAssay;
  projectCode: string;
  mode: "agent" | "pipeline";
  inputPath: string;
  dnaPaths?: string[];
  instructions: string;
  name?: string;
  options?: LabRunOptions;
  /** Create the project (folder + Active planner project) before launching. */
  newProject?: boolean;
}): Promise<LabRun> {
  const existing = await getLabRun(input.clientRequestId);
  if (existing) return existing;
  const env = getLabEnvironment();
  if (env.problems.length) throw new Error(env.problems.join(" "));
  // Check the data path before creating anything, so a mistyped path never
  // leaves a new, empty project behind.
  if (!existsSync(input.inputPath.trim().replace(/^"|"$/g, ""))) {
    throw new Error(`That input path does not exist on this machine: ${input.inputPath}`);
  }
  if (input.newProject) {
    input = { ...input, projectCode: (await createLabProject(input.projectCode)).code };
  }
  if (!(await folderFor(input.projectCode))) {
    throw new Error(`No project folder for ${input.projectCode} under Research-Private/10_Projects.`);
  }
  if (!(await isActiveLabProject(input.projectCode))) {
    throw new Error(`${input.projectCode} is not Active in the planner. Set it to Active to launch runs for it.`);
  }
  const run: LabRun = {
    id: input.clientRequestId,
    assay: input.assay,
    projectCode: input.projectCode,
    mode: input.mode,
    inputPath: input.inputPath.trim().replace(/^"|"$/g, ""),
    dnaPaths: input.dnaPaths?.filter(Boolean) ?? [],
    instructions: input.instructions,
    name: input.name,
    options: input.options,
    status: "queued",
    phase: "waiting",
    createdAt: new Date().toISOString(),
  };
  const file = runPath(run.id);
  await fs.mkdir(RUNS_DIR, { recursive: true });
  await fs.writeFile(file, JSON.stringify(run, null, 2), { encoding: "utf8", flag: "wx" });
  const child = spawn(PYTHON, [RUN_SCRIPT, "--run-id", run.id], {
    cwd: REPO,
    detached: true,
    stdio: "ignore",
    windowsHide: true,
    env: { ...process.env, CLAUDE_INVOKED_BY: "lab-run", PYTHONUTF8: "1" },
  });
  child.on("error", (error) => {
    void writeJsonAtomic(file, {
      ...run,
      status: "failed",
      phase: "finished",
      finishedAt: new Date().toISOString(),
      error: `Could not start the lab runner: ${error.message}`,
    });
  });
  child.unref();
  return run;
}

export async function getLabRun(id: string): Promise<LabRun | null> {
  let file: string;
  try {
    file = runPath(id);
  } catch {
    return null;
  }
  try {
    const run = JSON.parse(await fs.readFile(file, "utf8")) as LabRun;
    const reference = Date.parse(run.heartbeatAt || run.startedAt || run.createdAt);
    // A queued run may legitimately wait behind another for hours (one run
    // at a time); a running one heartbeats every few seconds.
    const staleAfter = run.status === "queued" ? 6 * 60 * 60_000 : 20 * 60_000;
    if (LIVE.includes(run.status) && Number.isFinite(reference) && Date.now() - reference > staleAfter) {
      const stale: LabRun = {
        ...run,
        status: run.status === "cancel_requested" ? "cancelled" : "failed",
        phase: "finished",
        finishedAt: new Date().toISOString(),
        error: "This detached run stopped reporting and was marked interrupted.",
      };
      await writeJsonAtomic(file, stale);
      return stale;
    }
    return run;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

export async function listLabRuns(limit = 10, opts: { includeDismissed?: boolean } = {}): Promise<LabRun[]> {
  let names: string[];
  try {
    names = await fs.readdir(RUNS_DIR);
  } catch {
    return [];
  }
  const runs = await Promise.all(
    names
      .filter((n) => n.endsWith(".json") && RUN_ID.test(n.slice(0, -5)))
      .map((n) => getLabRun(n.slice(0, -5)).catch(() => null)),
  );
  return runs
    .filter((r): r is LabRun => Boolean(r?.createdAt))
    .filter((r) => opts.includeDismissed || !r.dismissedAt)
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
    .slice(0, Math.max(1, Math.min(limit, 50)));
}

export async function cancelLabRun(id: string): Promise<LabRun> {
  const current = await getLabRun(id);
  if (!current) throw new Error("Lab run not found.");
  if (!LIVE.includes(current.status)) return current;
  await new Promise<void>((resolve, reject) => {
    const child = spawn(PYTHON, [RUN_SCRIPT, "--run-id", id, "--cancel"], { cwd: REPO, windowsHide: true });
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve() : reject(new Error("Could not cancel the lab run."))));
  });
  return (await getLabRun(id)) ?? current;
}

/** Clear a finished run off the monitor. The run file is kept (soft, like every dismiss here). */
export async function dismissLabRun(id: string): Promise<void> {
  const current = await getLabRun(id);
  if (!current) throw new Error("Lab run not found.");
  if (LIVE.includes(current.status)) throw new Error("Stop this run before clearing it.");
  if (current.dismissedAt) return;
  await writeJsonAtomic(runPath(id), { ...current, dismissedAt: new Date().toISOString() });
}
