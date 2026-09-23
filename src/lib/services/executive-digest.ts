import fs from "node:fs/promises";
import path from "node:path";
import { parseFrontmatter } from "./secondbrain";
import { listManifests } from "./teams";

const REPO = process.cwd();
const MEMORY = path.join(REPO, "VAULT", "Memory");
const STATE_FILE = path.join(
  REPO,
  ".claude",
  "data",
  "state",
  "ceo-brief-state.json",
);

/**
 * Decision-oriented team outputs only. Drafts, wiki pages, and daily logs are
 * intentionally excluded: they are useful records, but letting them outrank a
 * security audit or project pulse would make the Home brief noisy.
 */
const REPORT_DIRS = [
  { teamId: "research", relPath: "research/digests" },
  { teamId: "research", relPath: "projects" },
  { teamId: "research", relPath: "meetings/actions" },
  { teamId: "admin", relPath: "admin/commitments" },
  { teamId: "admin", relPath: "admin" },
  { teamId: "security", relPath: "security" },
] as const;

const NOT_REPORTS = new Set([
  "calendar-writes.md",
  "index.md",
  "README.md",
]);

export type ExecutiveDigestTone = "attention" | "watch" | "update";

export interface ExecutiveDigest {
  key: string;
  teamId: string;
  teamName: string;
  reportTitle: string;
  headline: string;
  highlights: string[];
  relPath: string;
  updatedIso: string;
  tone: ExecutiveDigestTone;
  signal: string;
  reportDate: string;
  dismissed: boolean;
  /**
   * This report is one paper's review, so it can be filed in the Rho library.
   * A project pulse or a meeting's action list has no citation to save, and offering to save one would be a control that cannot
   * work.
   */
  paperDigest: boolean;
}

interface Candidate {
  teamId: string;
  relPath: string;
  absPath: string;
  updatedIso: string;
  reportDate: string;
}

export interface DailyExecutiveBrief {
  research: ExecutiveDigest[];
  attention: ExecutiveDigest[];
  dismissedCount: number;
}

interface ExecutiveBriefState {
  dismissed: string[];
}

function cleanInline(value: string): string {
  return value
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_~]/g, "")
    .replace(/<[^>]+>/g, "")
    .replace(/\s*\((?:source|sources)\)\s*$/i, "")
    .replace(/\s+(?:source|sources):\s+https?:\/\/\S.*$/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

function shorten(value: string, max = 300): string {
  const clean = cleanInline(value);
  if (clean.length <= max) return clean;
  const slice = clean.slice(0, max + 1);
  const sentenceEnd = Math.max(
    slice.lastIndexOf(". "),
    slice.lastIndexOf("? "),
    slice.lastIndexOf("! "),
  );
  if (sentenceEnd >= Math.floor(max * 0.55)) return slice.slice(0, sentenceEnd + 1);
  const wordEnd = slice.lastIndexOf(" ");
  return `${slice.slice(0, wordEnd > 0 ? wordEnd : max).trim()}...`;
}

/**
 * Body of one section, by heading text.
 *
 * Matches H2 *or* H3: lit-review digests group their canonical fields under
 * three H2s and demote the field names ("Key Result", "Relevance To Your
 * Interests") to H3. An `##`-only pattern silently returned "" for every one of
 * them, which emptied the research half of the Home brief rather than failing.
 */
function section(body: string, heading: string): string {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = body.match(
    new RegExp(
      `(?:^|\\r?\\n)#{2,3}\\s+${escaped}\\s*\\r?\\n([\\s\\S]*?)(?=\\r?\\n#{2,3}\\s+|$)`,
      "i",
    ),
  );
  return match?.[1].trim() ?? "";
}

function subsection(body: string, heading: string): string {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = body.match(
    new RegExp(
      `(?:^|\\r?\\n)###\\s+${escaped}\\s*\\r?\\n([\\s\\S]*?)(?=\\r?\\n(?:##|###)\\s+|$)`,
      "i",
    ),
  );
  return match?.[1].trim() ?? "";
}

function reviewSection(body: string, heading: string): string {
  return section(body, heading) || subsection(body, heading);
}

/**
 * The verdict line from a lit-review digest.
 *
 * By convention the first blockquote in these files is the verdict: a label
 * line, the one-sentence rationale, then a "Next action:" line. The rationale is
 * the single best headline available, and for a screened (low-relevance) digest
 * it is the only prose in the file.
 */
function verdictNarrative(body: string): string {
  const match = body.match(/(?:^|\n)((?:[ \t]*>[^\n]*\n?)+)/);
  if (!match) return "";
  const lines = match[1]
    .split(/\r?\n/)
    .map((line) => line.replace(/^[ \t]*>[ \t]?/, "").trim())
    .filter(Boolean);
  const rationale = lines.filter(
    (line) => !/^\*\*(?:VERDICT|EVIDENCE GAP)\b/i.test(line) && !/^\*\*Next action:/i.test(line),
  );
  return cleanInline(rationale.join(" "));
}

function firstNarrative(value: string): string {
  const paragraphs = value
    .replace(/```[\s\S]*?```/g, "")
    .split(/\r?\n\s*\r?\n/)
    .map((block) =>
      block
        .split(/\r?\n/)
        .filter((line) => !/^\s*(?:#{1,6}\s|[-*+]\s|>\s|---+$)/.test(line))
        .join(" "),
    )
    .map(cleanInline)
    .filter(Boolean);
  return paragraphs[0] ?? "";
}

function firstReportNarrative(body: string): string {
  const withoutTitle = body.replace(/^#\s+.*$/m, "");
  const beforeFirstSection = withoutTitle.split(/\r?\n##\s+/)[0] ?? "";
  return firstNarrative(beforeFirstSection);
}

function extractItems(value: string): string[] {
  const headingItems = Array.from(value.matchAll(/^###\s+(.+)$/gm), (m) =>
    cleanInline(m[1]),
  );
  const listItems = Array.from(
    value.matchAll(/^\s*(?:[-*+]|\d+\.)\s+(?:\*\*)?(.+?)(?:\*\*)?\s*$/gm),
    (m) => cleanInline(m[1]),
  );
  return [...headingItems, ...listItems]
    .filter(Boolean)
    .map((item) => shorten(item, 180));
}

function unique(items: string[]): string[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = item.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function digestTone(
  teamId: string,
  frontmatter: Record<string, string>,
  body: string,
): { tone: ExecutiveDigestTone; signal: string } {
  const severity = frontmatter.highest_severity?.toLowerCase();
  const status = frontmatter.status?.toLowerCase();
  if (frontmatter.type?.toLowerCase() === "lit-review") {
    const relevance = frontmatter.relevance?.toLowerCase();
    if (relevance === "high") {
      return { tone: "attention", signal: "High relevance" };
    }
    if (relevance === "medium") {
      return { tone: "watch", signal: "Worth a look" };
    }
    if (relevance === "low") {
      return { tone: "update", signal: "Screened" };
    }
  }
  if (
    severity === "critical" ||
    severity === "high" ||
    status === "needs_review" ||
    /\b(?:decision|approval)\s+(?:needed|required)\b/i.test(body)
  ) {
    return { tone: "attention", signal: "Attention recommended" };
  }
  if (/^##\s+Worth watching/im.test(body)) {
    return { tone: "watch", signal: "Monitor" };
  }
  return { tone: "update", signal: "Latest update" };
}

function buildHeadline(
  body: string,
  frontmatter: Record<string, string>,
): string {
  if (frontmatter.type?.toLowerCase() === "lit-review") {
    // The verdict is written to be the one line worth reading, so it outranks
    // any section - and on a screened digest it is the only prose there is.
    const verdict = verdictNarrative(body);
    if (verdict) return shorten(verdict);
    // These are the `###` field labels the digest writer emits
    // (.claude/scripts/jobs/research_lit_review.py). Renaming a heading on one
    // side silently empties the research half of /today — change them together.
    for (const name of [
      "Relevance to your interests",
      "Relevance to your work",
      "Key methodological advance",
      "Key result",
      "Worth stealing",
    ]) {
      const narrative = firstNarrative(reviewSection(body, name));
      if (narrative) return shorten(narrative);
    }
  }

  const preferredSections = [
    "The one thing",
    "Executive summary",
    "Summary",
    "Bottom line",
    "Suggested focus",
  ];

  for (const name of preferredSections) {
    const narrative = firstNarrative(section(body, name));
    if (narrative) return shorten(narrative);
  }

  const intro = firstReportNarrative(body);
  if (intro) return shorten(intro);

  for (const name of ["Findings", "What moved", "Open questions"]) {
    const items = extractItems(section(body, name));
    if (items[0]) return shorten(items[0]);
  }

  return "A new team report is ready.";
}

function buildHighlights(
  body: string,
  headline: string,
  frontmatter: Record<string, string>,
): string[] {
  if (frontmatter.type?.toLowerCase() === "lit-review") {
    // A screened digest has no canonical sections at all - three bullets under
    // "Screening note" is the whole review, by design.
    const screening = extractItems(section(body, "Screening note"));
    if (screening.length) {
      return unique(screening)
        .filter((item) => item.toLowerCase() !== headline.toLowerCase())
        .slice(0, 3);
    }
    return unique(
      [
        "Key methodological advance",
        "Real-life application implications",
        "Key result",
        "Relevance to your interests",
        "Relevance to your work",
        "Worth stealing",
        "Caveats",
      ]
        .map((name) => firstNarrative(reviewSection(body, name)))
        .filter(Boolean)
        .map((item) => shorten(item, 180)),
    )
      .filter((item) => item.toLowerCase() !== headline.toLowerCase())
      .slice(0, 3);
  }

  const preferredSections = [
    "Actions required",
    "Recommendations",
    "Worth watching",
    "Open questions",
    "Findings",
    "What moved",
    "Key findings",
  ];
  const items: string[] = [];

  for (const name of preferredSections) {
    items.push(...extractItems(section(body, name)));
    if (items.length >= 3) break;
  }

  return unique(items)
    .filter((item) => item.toLowerCase() !== headline.toLowerCase())
    .slice(0, 3);
}

function reportDate(name: string, updatedIso: string): string {
  return name.match(/^(\d{4}-\d{2}-\d{2})/)?.[1] ?? updatedIso.slice(0, 10);
}

async function listCandidates(): Promise<Candidate[]> {
  const candidates: Candidate[] = [];

  for (const source of REPORT_DIRS) {
    const absDir = path.join(MEMORY, source.relPath);
    let names: string[];
    try {
      names = await fs.readdir(absDir);
    } catch {
      continue;
    }

    for (const name of names) {
      if (
        !name.endsWith(".md") ||
        name.startsWith(".") ||
        NOT_REPORTS.has(name)
      ) {
        continue;
      }
      const absPath = path.join(absDir, name);
      try {
        const stat = await fs.stat(absPath);
        if (!stat.isFile()) continue;
        candidates.push({
          teamId: source.teamId,
          relPath: `${source.relPath}/${name}`,
          absPath,
          updatedIso: stat.mtime.toISOString(),
          reportDate: reportDate(name, stat.mtime.toISOString()),
        });
      } catch {
        continue;
      }
    }
  }

  return candidates.sort((a, b) => b.updatedIso.localeCompare(a.updatedIso));
}

async function readState(): Promise<ExecutiveBriefState> {
  try {
    const raw = JSON.parse(await fs.readFile(STATE_FILE, "utf8")) as Partial<ExecutiveBriefState>;
    return {
      dismissed: Array.isArray(raw.dismissed)
        ? raw.dismissed.filter((key): key is string => typeof key === "string")
        : [],
    };
  } catch {
    return { dismissed: [] };
  }
}

async function writeState(state: ExecutiveBriefState) {
  await fs.mkdir(path.dirname(STATE_FILE), { recursive: true });
  const temp = `${STATE_FILE}.${process.pid}.tmp`;
  await fs.writeFile(temp, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  await fs.rename(temp, STATE_FILE);
}

async function buildDigest(
  candidate: Candidate,
  teamNames: Map<string, string>,
  dismissed: Set<string>,
): Promise<ExecutiveDigest | null> {
  const raw = await fs.readFile(candidate.absPath, "utf8").catch(() => "");
  if (!raw) return null;

  const { fm, body } = parseFrontmatter(raw);
  const teamName = teamNames.get(candidate.teamId) ?? candidate.teamId;
  const reportTitle =
    cleanInline(fm.title ?? "") ||
    cleanInline(body.match(/^#\s+(.+)$/m)?.[1] ?? "") ||
    path.basename(candidate.relPath, ".md").replace(/[-_]+/g, " ");
  const headline = buildHeadline(body, fm);
  const { tone, signal } = digestTone(candidate.teamId, fm, body);
  const key = `${candidate.relPath}::${candidate.updatedIso}`;

  return {
    key,
    teamId: candidate.teamId,
    teamName,
    reportTitle,
    headline,
    highlights: buildHighlights(body, headline, fm),
    relPath: candidate.relPath,
    updatedIso: candidate.updatedIso,
    tone,
    signal,
    reportDate: candidate.reportDate,
    dismissed: dismissed.has(key),
    paperDigest: fm.type?.toLowerCase() === "lit-review",
  };
}

function latestBundle(
  digests: ExecutiveDigest[],
  teamId: string,
): ExecutiveDigest[] {
  const team = digests.filter((digest) => digest.teamId === teamId);
  const latestDate = team[0]?.reportDate;
  if (!latestDate) return [];
  return team.filter((digest) => digest.reportDate === latestDate).slice(0, 8);
}

/** Return the latest daily bundle: Scientific Research plus attention items. */
export async function getDailyExecutiveBrief(): Promise<DailyExecutiveBrief> {
  const [candidates, manifests, state] = await Promise.all([
    listCandidates(),
    listManifests(),
    readState(),
  ]);
  const teamNames = new Map(manifests.map((manifest) => [manifest.id, manifest.name]));
  const dismissed = new Set(state.dismissed);
  const built = await Promise.all(
    candidates.map((candidate) => buildDigest(candidate, teamNames, dismissed)),
  );
  const digests = built.filter((digest): digest is ExecutiveDigest => Boolean(digest));
  const research = latestBundle(digests, "research");
  const attention = ["admin", "security"]
    .flatMap((teamId) => latestBundle(digests, teamId))
    .filter((digest) => digest.tone === "attention")
    .slice(0, 3);
  return {
    research,
    attention,
    dismissedCount: [...research, ...attention].filter(
      (digest) => digest.dismissed,
    ).length,
  };
}

export async function dismissExecutiveDigest(key: string): Promise<void> {
  if (!key || key.length > 1000 || !key.includes("::")) {
    throw new Error("Invalid CEO Brief report key.");
  }
  const state = await readState();
  const dismissed = new Set(state.dismissed);
  dismissed.add(key);
  await writeState({ dismissed: [...dismissed].slice(-500) });
}

export async function restoreExecutiveDigests(): Promise<void> {
  await writeState({ dismissed: [] });
}

/** Backward-compatible single-report helper. */
export async function getLatestExecutiveDigest(): Promise<ExecutiveDigest | null> {
  const [candidate] = await listCandidates();
  if (!candidate) return null;
  const [manifests, state] = await Promise.all([listManifests(), readState()]);
  const teamNames = new Map(manifests.map((manifest) => [manifest.id, manifest.name]));
  return buildDigest(candidate, teamNames, new Set(state.dismissed));
}
