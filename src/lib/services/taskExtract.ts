import { db } from "@/lib/db";
import { OPEN_TASK_STATUSES, TASK_CONTEXTS } from "@/lib/types";

/**
 * Turn the free text the owner actually writes into task candidates.
 *
 * Two surfaces feed this: the Today daily note (sections like `@lab` with
 * `[ ]` lines) and a review's "Next priorities" (bullet lines, no sections).
 * They are one idea — "this text describes work that should exist as tasks" —
 * so they share one parser and one preview dialog rather than growing two.
 *
 * Nothing here writes. The parser proposes; the preview is where they decide.
 */

export type TaskCandidate = {
  /** Stable key for React and for selection round-tripping. */
  key: string;
  title: string;
  description: string | null;
  context: string | null;
  projectId: string | null;
  /** The `@section` this line sat under, shown so the grouping is legible. */
  section: string | null;
  /** An open task already carries this title — offered, but not preselected. */
  duplicate: boolean;
  /** YYYY-MM-DD, for candidates that carry a date (an application plan). */
  dueDate?: string | null;
};

const CONTEXT_SET = new Set<string>(TASK_CONTEXTS);

/** Loose match key: casing, spacing, and punctuation are not signal here. */
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** `@lab`, `@CBIC`, `@G2,` — a section header, optionally comma/colon-tailed. */
const SECTION_RE = /^@([\w &/'-]{1,40})[,:\s]*$/;
/** `[ ] thing`, `[] thing`, `- [x] thing`. Group 1 is the check state. */
const CHECKBOX_RE = /^[-*+]?\s*\[([ xX]?)\]\s*(.*)$/;
/** Leading `-`, `*`, `1.`, `2)` on an ordinary bullet line. */
const BULLET_RE = /^(?:[-*+]|\d+[.)])\s+/;
/** `Alpha: finish the analysis` — a project name claiming the line. */
const PREFIX_RE = /^([A-Za-z][\w &/'()-]{0,40}):\s+(\S.*)$/;

const MAX_TITLE = 300;

/** Split an overlong line into a title plus the full text as description. */
function splitLongLine(body: string): { title: string; description: string | null } {
  if (body.length <= MAX_TITLE) return { title: body, description: null };
  const sentenceEnd = body.slice(0, MAX_TITLE).search(/[.;!?](?=\s|$)/);
  const cut = sentenceEnd > 20 ? sentenceEnd + 1 : MAX_TITLE;
  return { title: body.slice(0, cut).trim(), description: body };
}

export type ParseOptions = {
  projects: Array<{ id: string; title: string }>;
  /** Normalized titles of open tasks, so a second pull does not duplicate. */
  existingTitles?: Set<string>;
  /** Daily-note text uses `@section` headers; review priorities do not. */
  sections?: boolean;
};

/**
 * Pure parser — no I/O, so it can be reasoned about and tested directly.
 *
 * Checked lines (`[x]`) are dropped: they describe work already done, and a
 * pre-completed task is noise in every view that would show it.
 */
export function parsePlanText(text: string, opts: ParseOptions): TaskCandidate[] {
  const { projects, existingTitles = new Set<string>(), sections = true } = opts;
  const projectByName = new Map(projects.map((p) => [norm(p.title), p.id]));

  const out: TaskCandidate[] = [];
  const seen = new Set<string>();
  let section: string | null = null;
  let sectionContext: string | null = null;
  let sectionProjectId: string | null = null;

  text.split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) return;

    if (sections) {
      const header = SECTION_RE.exec(line);
      if (header) {
        section = header[1].trim();
        const key = norm(section);
        sectionContext = CONTEXT_SET.has(key) ? key : null;
        sectionProjectId = sectionContext ? null : (projectByName.get(key) ?? null);
        return;
      }
    }

    let body = line;
    const checkbox = CHECKBOX_RE.exec(line);
    if (checkbox) {
      if (checkbox[1].toLowerCase() === "x") return; // already done
      body = checkbox[2].trim();
    } else {
      body = line.replace(BULLET_RE, "").trim();
    }
    if (!body) return;

    // An inline `Project:` prefix is more specific than the section, so it wins.
    let projectId = sectionProjectId;
    const prefix = PREFIX_RE.exec(body);
    if (prefix) {
      const matched = projectByName.get(norm(prefix[1]));
      if (matched) {
        projectId = matched;
        body = prefix[2].trim();
      }
    }

    const { title, description } = splitLongLine(body);
    const key = norm(title);
    if (!key || seen.has(key)) return;
    seen.add(key);

    out.push({
      key: `${index}-${key.slice(0, 24)}`,
      title,
      description,
      context: sectionContext,
      projectId,
      section,
      duplicate: existingTitles.has(key),
    });
  });

  return out;
}

/**
 * Parse against live projects and open tasks.
 *
 * The duplicate check is what makes pulling twice in one day safe — they edit
 * the note all day, and the second pull should offer only what is new.
 */
export async function buildTaskCandidates(
  text: string,
  opts: { sections?: boolean } = {},
): Promise<{ candidates: TaskCandidate[]; projects: Array<{ id: string; title: string }> }> {
  const [projects, openTasks] = await Promise.all([
    db.project.findMany({
      where: { archivedAt: null, status: { in: ["active", "inbox", "paused"] } },
      select: { id: true, title: true },
      orderBy: { title: "asc" },
    }),
    db.task.findMany({
      where: { archivedAt: null, status: { in: OPEN_TASK_STATUSES } },
      select: { title: true },
    }),
  ]);

  const existingTitles = new Set(openTasks.map((t) => norm(t.title)));
  return {
    candidates: parsePlanText(text, { projects, existingTitles, sections: opts.sections }),
    projects,
  };
}
