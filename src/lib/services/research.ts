import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { db } from "@/lib/db";
import { fetchJournalFeeds } from "@/lib/services/journals";
import { getJob, listJobs, type JobStatus } from "@/lib/services/ledger";
import { parseFrontmatter, readVaultFile } from "@/lib/services/secondbrain";

const REPO = process.cwd();
const PYTHON =
  process.env.SECONDBRAIN_PYTHON ||
  "python";
const SCRIPT = path.join(REPO, ".claude", "scripts", "research_review.py");
const BIB_EVENTS = path.join(
  REPO,
  ".claude",
  "data",
  "research",
  "bibliography-events.jsonl",
);
const DIGEST_DIR = path.join(REPO, "VAULT", "Memory", "research", "digests");
const DIGEST_REL = "research/digests";
const DOI_RE = /^10\.\d{4,9}\/[-._;()/:a-z0-9]+$/i;

export type ResearchReviewRequest = {
  clientRequestId: string;
  source: "doi" | "feed";
  targetType?: "project" | "resource";
  targetId?: string;
  doi?: string;
  feedKey?: string;
  sourceRef?: string;
};

export type ResearchTargetType = "project" | "resource" | "area";

export type ResearchTarget = {
  type: ResearchTargetType;
  id: string;
};

export type ResearchReviewLaunch = {
  itemId: string;
  jobId: string | null;
  status: string;
  savedOnly: boolean;
  reused: boolean;
  message?: string;
};

export type ResearchReviewStatus = {
  jobId: string;
  status: JobStatus;
  title: string;
  digestPath: string | null;
  error: string | null;
};

type Author = { given?: string; family?: string; literal?: string };
type BibMetadata = {
  title?: string;
  authors?: Author[];
  author_text?: string;
  abstract?: string;
  published_at?: string;
  journal?: string;
  source?: string;
  url?: string;
  doi?: string;
  preprint_doi?: string;
};

export type BibliographyItem = {
  itemId: string;
  title: string;
  authors: Author[];
  authorText: string;
  abstract: string;
  publishedAt: string;
  journal: string;
  source: string;
  url: string;
  doi: string;
  preprintDoi: string;
  projects: Array<{ id: string; title: string }>;
  resources: Array<{ id: string; title: string }>;
  areas: Array<{ id: string; title: string }>;
  latestReviewJobId: string | null;
  digestPath: string | null;
};

type FoldedItem = {
  item_id: string;
  identifiers: Record<string, string>;
  metadata: BibMetadata;
  projects: Record<string, string>;
  resources: Record<string, string>;
  areas: Record<string, string>;
  archived: boolean;
  latest_review_job_id: string | null;
  digest_path: string | null;
};

/**
 * The URL form used for identity comparisons.
 *
 * Mirrors `canonical_url()` in research_review.py, which is what actually
 * normalizes a stored identifier. Both sides of every comparison here are run
 * through *this* function - the stored value as well as the incoming one - so a
 * drift between the two implementations can only cost a link, never attach a
 * digest to the wrong paper.
 */
function canonicalUrl(value: string): string {
  const raw = (value || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw);
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    for (const key of [...url.searchParams.keys()]) {
      if (key.toLowerCase().startsWith("utm_")) url.searchParams.delete(key);
    }
    const query = url.searchParams.toString();
    const trimmed = url.pathname.replace(/\/+$/, "");
    return `${url.protocol}//${url.host.toLowerCase()}${trimmed}${query ? `?${query}` : ""}`;
  } catch {
    return "";
  }
}

/**
 * Identity keys for one paper: canonical article URL and DOI.
 *
 * Title is deliberately not a key. Preprint v1/v2 and the journal version of
 * one paper share a title, and attaching the wrong review to a citation is
 * worse than showing no review link at all.
 */
function identityKeys(values: {
  url?: string;
  doi?: string;
  paperId?: string;
}): string[] {
  const keys: string[] = [];
  const url = canonicalUrl(values.url ?? "");
  if (url) keys.push(`url:${url}`);
  for (const candidate of [values.doi, values.paperId]) {
    const doi = (candidate ?? "").trim().toLowerCase();
    if (DOI_RE.test(doi)) keys.push(`doi:${doi}`);
  }
  return keys;
}

/** Author lists arrive as one string from every upstream source. */
function splitAuthors(authorText: string): Author[] {
  return authorText
    ? authorText
        .split(/\s*;\s*|\s*,\s*(?=[A-Z][a-z]+\s+[A-Z])/)
        .map((literal) => literal.trim())
        .filter(Boolean)
        .map((literal) => ({ literal }))
    : [];
}

function normalizeDoi(value: string): string {
  const doi = decodeURIComponent(value.trim())
    .replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i, "")
    .replace(/[.,;]+$/, "")
    .toLowerCase();
  if (!DOI_RE.test(doi)) {
    throw new Error("Enter a valid DOI, such as 10.1101/2026.01.02.123456.");
  }
  return doi;
}

function runPython<T extends object>(
  command: "enqueue" | "archive" | "reclassify",
  input: unknown,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const child = spawn(PYTHON, [SCRIPT, command], {
      cwd: REPO,
      shell: false,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env, CLAUDE_INVOKED_BY: "rho-on-demand" },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      if (stdout.length < 64_000) stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      if (stderr.length < 16_000) stderr += chunk;
    });
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Paper metadata lookup timed out."));
    }, 45_000);
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      let parsed: (T & { error?: string }) | null = null;
      try {
        parsed = JSON.parse(stdout.trim());
      } catch {
        reject(new Error(stderr.trim() || "Rho returned an unreadable response."));
        return;
      }
      if (!parsed || code !== 0 || parsed.error) {
        reject(new Error(parsed?.error || stderr.trim() || "Rho could not save this paper."));
        return;
      }
      resolve(parsed);
    });
    child.stdin.end(JSON.stringify(input));
  });
}

function launchJob(jobId: string): void {
  const child = spawn(PYTHON, [SCRIPT, "run", "--job-id", jobId], {
    cwd: REPO,
    detached: true,
    shell: false,
    windowsHide: true,
    stdio: "ignore",
    env: { ...process.env, CLAUDE_INVOKED_BY: "rho-on-demand" },
  });
  child.unref();
}

const BRAINSTORMING_AREA_ID = "rho-brainstorming";

/**
 * Brainstorming is a **resource domain**, not a responsibility: an Area with
 * `type: "resource"`, so /areas lists it under "Resource domains" alongside the
 * other topic buckets. Papers landing here are not a standing obligation you
 * maintain — they are unfiled reading.
 *
 * `type` is repaired on every read because the row shipped as `type: "area"`
 * and there is no migration for a single string column; the first save after
 * this change moves it, and a manual edit back is respected only until the next
 * paper arrives.
 */
async function brainstormingArea() {
  const existing = await db.area.findFirst({
    where: { title: "Brainstorming" },
    select: { id: true, title: true, archivedAt: true, type: true },
  });
  if (existing) {
    if (existing.archivedAt || existing.type !== "resource") {
      return db.area.update({
        where: { id: existing.id },
        data: { archivedAt: null, type: "resource" },
        select: { id: true, title: true },
      });
    }
    return { id: existing.id, title: existing.title };
  }
  return db.area.upsert({
    where: { id: BRAINSTORMING_AREA_ID },
    update: { archivedAt: null, title: "Brainstorming", type: "resource" },
    create: {
      id: BRAINSTORMING_AREA_ID,
      title: "Brainstorming",
      description:
        "Unfiled literature. Each paper gets its own resource here until it is routed to a project, area, or resource domain.",
      type: "resource",
      icon: "lightbulb",
    },
    select: { id: true, title: true },
  });
}

/**
 * The Brainstorming area id, or null before the first paper creates it.
 *
 * Callers use it to keep the "Resource" target pickers meaningful: every
 * unfiled paper materializes a Resource row inside this area, so without the
 * filter those dropdowns would fill with hundreds of individual papers and stop
 * being a list of domains.
 */
export async function getBrainstormingAreaId(): Promise<string | null> {
  const area = await db.area.findFirst({
    where: { title: "Brainstorming" },
    select: { id: true },
  });
  return area?.id ?? null;
}

/** Stable per-paper key: the DOI when there is one, else the article link. */
function paperKey(doi: string, url: string): string {
  const normalized = doi.trim().toLowerCase();
  return normalized ? `https://doi.org/${normalized}` : url.trim();
}

type PaperSeed = { doi: string; url: string; title: string; summary: string };

/**
 * The dedicated Resource row for one unfiled paper, inside Brainstorming.
 *
 * Idempotent on (Brainstorming area, paper key) rather than on title: enqueue
 * is DOI-keyed and can legitimately run twice for the same paper, and a
 * DOI-only submission has no title until the Python side has resolved Crossref.
 * That is also why the title can start as the key and get backfilled by
 * `syncPaperResource` once enqueue returns real metadata.
 */
async function brainstormingPaperResource(seed: PaperSeed) {
  const area = await brainstormingArea();
  const key = paperKey(seed.doi, seed.url);
  const existing = key
    ? await db.resource.findFirst({
        where: { areaId: area.id, url: key },
        select: { id: true, title: true, archivedAt: true },
      })
    : null;
  if (existing) {
    if (existing.archivedAt) {
      return db.resource.update({
        where: { id: existing.id },
        data: { archivedAt: null },
        select: { id: true, title: true },
      });
    }
    return { id: existing.id, title: existing.title };
  }
  return db.resource.create({
    data: {
      title: seed.title.trim() || key || "Untitled paper",
      url: key || null,
      type: "article",
      status: "inbox",
      summary: seed.summary.trim() ? seed.summary.slice(0, 2_000) : null,
      areaId: area.id,
    },
    select: { id: true, title: true },
  });
}

/** Backfill a placeholder paper resource once enqueue has resolved metadata. */
async function syncPaperResource(resourceId: string, itemId: string) {
  const item = foldBibliography().find((candidate) => candidate.itemId === itemId);
  if (!item || !item.title || item.title === "(untitled)") return;
  const current = await db.resource.findUnique({
    where: { id: resourceId },
    select: { title: true, summary: true, url: true },
  });
  if (!current) return;
  const looksLikeKey = current.title === current.url || current.title === "Untitled paper";
  await db.resource.update({
    where: { id: resourceId },
    data: {
      ...(looksLikeKey ? { title: item.title } : {}),
      ...(current.summary ? {} : { summary: item.abstract.slice(0, 2_000) || null }),
      ...(current.url ? {} : { url: item.url || null }),
    },
  });
}

async function resolveResearchTarget(target?: ResearchTarget, seed?: PaperSeed) {
  if (!target) {
    // No destination chosen: the paper becomes its own resource in the
    // Brainstorming domain rather than a bare area-level tag, so it is a real
    // library entry you can open, annotate, and later move.
    const resource = await brainstormingPaperResource(
      seed ?? { doi: "", url: "", title: "", summary: "" },
    );
    return { type: "resource" as const, ...resource, brainstormed: true };
  }
  if (target.type === "project") {
    const project = await db.project.findFirst({
      where: { id: target.id, archivedAt: null },
      select: { id: true, title: true },
    });
    if (!project) throw new Error("Choose an active project.");
    return { type: "project" as const, ...project, brainstormed: false };
  }
  if (target.type === "resource") {
    const resource = await db.resource.findFirst({
      where: { id: target.id, archivedAt: null },
      select: { id: true, title: true },
    });
    if (!resource) throw new Error("Choose an active resource.");
    return { type: "resource" as const, ...resource, brainstormed: false };
  }
  const area = await db.area.findFirst({
    where: { id: target.id, archivedAt: null },
    select: { id: true, title: true },
  });
  if (!area) throw new Error("Choose an active area.");
  return { type: "area" as const, ...area, brainstormed: false };
}

export async function requestPaperReview(
  input: ResearchReviewRequest,
): Promise<ResearchReviewLaunch> {
  if (Boolean(input.targetType) !== Boolean(input.targetId)) {
    throw new Error("Choose both a target type and destination, or neither.");
  }
  let doi = input.doi ? normalizeDoi(input.doi) : "";
  let metadata: Record<string, unknown> | undefined;
  if (input.source === "feed") {
    const feeds = await fetchJournalFeeds();
    const feed = feeds.find((candidate) => candidate.key === input.feedKey);
    const item = feed?.items.find(
      (candidate) =>
        candidate.link === input.sourceRef || candidate.doi === input.sourceRef,
    );
    if (!feed || !item) {
      throw new Error("That feed item is no longer available. Refresh and try again.");
    }
    doi = item.doi || "";
    metadata = {
      title: item.title,
      authors: splitAuthors(item.authors || ""),
      authorText: item.authors || "",
      summary: item.summary || "",
      publishedAt: item.publishedAt || "",
      journal: feed.label,
      source: feed.key,
      url: item.link,
      doi,
    };
  } else if (!doi) {
    throw new Error("Enter a DOI.");
  }

  // Resolved after metadata, not before: the Brainstorming fallback mints a
  // Resource row for this specific paper and needs its title and link.
  const target = await resolveResearchTarget(
    input.targetType && input.targetId
      ? { type: input.targetType, id: input.targetId }
      : undefined,
    {
      doi,
      url: String(metadata?.url ?? ""),
      title: String(metadata?.title ?? ""),
      summary: String(metadata?.summary ?? ""),
    },
  );

  const result = await runPython<ResearchReviewLaunch>("enqueue", {
    clientRequestId: input.clientRequestId,
    source: input.source,
    targetType: target.type,
    targetId: target.id,
    targetTitle: target.title,
    doi,
    metadata,
  });
  // Enqueue has now appended the resolved Crossref/bioRxiv metadata, so a
  // DOI-only submission can stop showing its own DOI as the resource title.
  if (target.brainstormed && result.itemId) {
    await syncPaperResource(target.id, result.itemId);
  }
  if (result.jobId && result.status === "created") launchJob(result.jobId);
  return result;
}

export async function archiveBibliographyItem(itemId: string) {
  const priorResourceIds = currentResourceIds(itemId);
  const result = await runPython<{
    itemId: string;
    archived: boolean;
    reused: boolean;
  }>("archive", { itemId });
  await retireBrainstormingResources(priorResourceIds);
  return result;
}

function currentResourceIds(itemId: string): string[] {
  const item = foldBibliography().find((candidate) => candidate.itemId === itemId);
  return (item?.resources ?? []).map((resource) => resource.id);
}

/**
 * Retire a paper's Brainstorming resource when it leaves that domain.
 *
 * Brainstorming is a staging bucket, so a paper routed on to a project — or
 * archived out of the bibliography — should not keep a row there. Scoped to the
 * Brainstorming area, so a real resource the paper was filed under is never
 * touched. Soft only: archived, never deleted, and the JSONL history is
 * untouched either way. The ids must be read *before* the reclassify/archive
 * call, since those append events that clear the old assignment.
 */
async function retireBrainstormingResources(ids: string[]) {
  if (!ids.length) return;
  const areaId = await getBrainstormingAreaId();
  if (!areaId) return;
  await db.resource.updateMany({
    where: { id: { in: ids }, areaId, archivedAt: null },
    data: { archivedAt: new Date() },
  });
}

export async function reclassifyBibliographyItem(
  itemId: string,
  target?: ResearchTarget,
) {
  // Seed the Brainstorming fallback from the bibliography, so a paper moved
  // back here gets a properly titled resource instead of a bare key.
  const known = foldBibliography().find((candidate) => candidate.itemId === itemId);
  const priorResourceIds = (known?.resources ?? []).map((resource) => resource.id);
  const resolved = await resolveResearchTarget(target, {
    doi: known?.doi || known?.preprintDoi || "",
    url: known?.url || "",
    title: known?.title === "(untitled)" ? "" : known?.title || "",
    summary: known?.abstract || "",
  });
  const result = await runPython<{
    itemId: string;
    targetType: ResearchTargetType;
    targetId: string;
    reused: boolean;
  }>("reclassify", {
    itemId,
    targetType: resolved.type,
    targetId: resolved.id,
    targetTitle: resolved.title,
  });
  await retireBrainstormingResources(
    priorResourceIds.filter((id) => id !== resolved.id),
  );
  return result;
}

/** The payload of the lit-review job that wrote one digest, if it is still in the ledger. */
async function digestJobPayload(relPath: string): Promise<Record<string, unknown>> {
  const jobs = await listJobs({ kind: "research.lit_review" });
  const match = jobs.find((job) => {
    const result = (job.result ?? {}) as Record<string, unknown>;
    return String(result.digest_path ?? "").replace(/\\/g, "/") === relPath;
  });
  return (match?.payload ?? {}) as Record<string, unknown>;
}

export type DigestSaveResult = {
  itemId: string;
  digestPath: string;
  targetType: ResearchTargetType;
  targetId: string;
};

/**
 * File an already-written lit-review digest into the Rho library.
 *
 * The daily research team enqueues papers with no bibliography entry, so a
 * digest read on the CEO Brief had nowhere to go: it could be opened and
 * dismissed, never kept against a project. This is the newsletter's
 * "Review + save" minus the review - the review is the digest the owner is looking
 * at - so **no model runs and no job is enqueued**. Two consequences worth
 * knowing:
 *
 * - No DOI is sent to `enqueue`. Supplying one makes research_review.py fetch
 *   Crossref/bioRxiv metadata, and a resolved abstract is exactly what makes
 *   `enqueue` create a review job. The paper is identified by its canonical
 *   URL instead, so saving is uniformly free of model spend rather than
 *   free-for-arXiv and a re-review for bioRxiv.
 * - A digest whose paper is already in the library is a move, not a second
 *   entry; that path goes through the existing reclassify command.
 */
export async function saveDigestToLibrary(
  digestPath: string,
  target?: ResearchTarget,
): Promise<DigestSaveResult> {
  const relPath = digestPath.replace(/\\/g, "/").replace(/^\/+/, "");
  // readVaultFile is the existing VAULT/Memory-scoped reader: it resolves the
  // path and refuses anything outside, so `../` cannot reach a private vault.
  const raw = await readVaultFile(relPath);
  if (raw === null) {
    throw new Error("That report is no longer in the vault.");
  }
  const { fm } = parseFrontmatter(raw);
  if ((fm.type ?? "").toLowerCase() !== "lit-review") {
    throw new Error("Only a paper review can be saved to the research library.");
  }
  const title = (fm.title ?? "").trim();
  if (!title || title === "(untitled)") {
    throw new Error("That review does not name a paper.");
  }
  const url = canonicalUrl(fm.url ?? "");
  if (!url) {
    // Without a stable identifier every save would mint another entry for the
    // same paper. Failing is better than a bibliography that quietly doubles.
    throw new Error("That review records no article link, so it cannot be filed.");
  }

  const existing = (await listBibliography()).find(
    (item) => item.digestPath === relPath,
  );
  if (existing) {
    const moved = await reclassifyBibliographyItem(existing.itemId, target);
    return {
      itemId: existing.itemId,
      digestPath: relPath,
      targetType: moved.targetType,
      targetId: moved.targetId,
    };
  }

  const payload = await digestJobPayload(relPath);
  const authorText = String(payload.authors ?? "").trim();
  const resolved = await resolveResearchTarget(target, {
    doi: "",
    url,
    title,
    summary: "",
  });
  const result = await runPython<ResearchReviewLaunch>("enqueue", {
    clientRequestId: randomUUID(),
    source: "digest",
    targetType: resolved.type,
    targetId: resolved.id,
    targetTitle: resolved.title,
    metadata: {
      title,
      authors: splitAuthors(authorText),
      authorText,
      // Deliberately empty: an abstract is what turns enqueue into a review.
      summary: "",
      journal: fm.journal ?? "",
      source: fm.source ?? "",
      url,
    },
  });
  return {
    itemId: result.itemId,
    digestPath: relPath,
    targetType: resolved.type,
    targetId: resolved.id,
  };
}

export async function getResearchReviewStatus(
  jobId: string,
): Promise<ResearchReviewStatus | null> {
  const job = await getJob(jobId);
  if (!job || job.kind !== "research.lit_review") return null;
  const payload = (job.payload ?? {}) as Record<string, unknown>;
  const result = (job.result ?? {}) as Record<string, unknown>;
  return {
    jobId,
    status: job.status,
    title: String(payload.title || "Paper review"),
    digestPath:
      typeof result.digest_path === "string" ? result.digest_path : null,
    error: job.error || null,
  };
}

let bibliographyCache:
  | { signature: string; items: BibliographyItem[] }
  | null = null;

function bibliographySignature(): string {
  try {
    const stat = statSync(BIB_EVENTS);
    return `${stat.size}:${stat.mtimeMs}`;
  } catch {
    return "missing";
  }
}

function foldBibliography(): BibliographyItem[] {
  const signature = bibliographySignature();
  if (bibliographyCache?.signature === signature) return bibliographyCache.items;
  const folded = new Map<string, FoldedItem>();
  let raw = "";
  try {
    raw = readFileSync(BIB_EVENTS, "utf8");
  } catch {
    bibliographyCache = { signature, items: [] };
    return [];
  }
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const event = JSON.parse(line) as Record<string, unknown>;
      const itemId = typeof event.item_id === "string" ? event.item_id : "";
      if (!itemId) continue;
      const item =
        folded.get(itemId) ??
        {
          item_id: itemId,
          identifiers: {},
          metadata: {},
          projects: {},
          resources: {},
          areas: {},
          archived: false,
          latest_review_job_id: null,
          digest_path: null,
        };
      if (event.event === "paper_selected" || event.event === "metadata_enriched") {
        Object.assign(item.identifiers, event.identifiers ?? {});
        Object.assign(item.metadata, event.metadata ?? {});
      } else if (event.event === "project_assigned") {
        item.projects[String(event.project_id || "")] = String(
          event.project_title || "",
        );
      } else if (event.event === "resource_assigned") {
        item.resources[String(event.resource_id || "")] = String(
          event.resource_title || "",
        );
      } else if (event.event === "area_assigned") {
        item.areas[String(event.area_id || "")] = String(
          event.area_title || "",
        );
      } else if (event.event === "paper_reclassified") {
        item.projects = {};
        item.resources = {};
        item.areas = {};
        const targetType = String(event.target_type || "");
        const targetId = String(event.target_id || "");
        const targetTitle = String(event.target_title || "");
        if (
          ["project", "resource", "area"].includes(targetType) &&
          targetId
        ) {
          const bucket =
            targetType === "project"
              ? item.projects
              : targetType === "resource"
                ? item.resources
                : item.areas;
          bucket[targetId] = targetTitle;
        }
      } else if (event.event === "paper_archived") {
        item.archived = true;
      } else if (event.event === "paper_restored") {
        item.archived = false;
      } else if (event.event === "review_linked") {
        item.latest_review_job_id = String(event.job_id || "") || null;
      } else if (event.event === "review_completed") {
        item.latest_review_job_id = String(event.job_id || "") || null;
        item.digest_path = String(event.digest_path || "") || null;
      }
      folded.set(itemId, item);
    } catch {
      // Ignore a partial trailing event; the append-only history remains intact.
    }
  }
  const items = [...folded.values()]
    .map((item): BibliographyItem => ({
      itemId: item.item_id,
      title: item.metadata.title || "(untitled)",
      authors: Array.isArray(item.metadata.authors) ? item.metadata.authors : [],
      authorText: item.metadata.author_text || "",
      abstract: item.metadata.abstract || "",
      publishedAt: item.metadata.published_at || "",
      journal: item.metadata.journal || "",
      source: item.metadata.source || "",
      url: item.metadata.url || "",
      doi: item.metadata.doi || item.identifiers.doi || "",
      preprintDoi:
        item.metadata.preprint_doi || item.identifiers.preprint_doi || "",
      projects: Object.entries(item.projects)
        .filter(([id]) => id)
        .map(([id, title]) => ({ id, title })),
      resources: Object.entries(item.resources)
        .filter(([id]) => id)
        .map(([id, title]) => ({ id, title })),
      areas: Object.entries(item.areas)
        .filter(([id]) => id)
        .map(([id, title]) => ({ id, title })),
      latestReviewJobId: item.latest_review_job_id,
      digestPath: item.digest_path,
    }))
    .filter((item) => {
      const foldedItem = folded.get(item.itemId);
      return !foldedItem?.archived;
    })
    .reverse();
  bibliographyCache = { signature, items };
  return items;
}

let digestCache: { signature: string; byIdentity: Map<string, string> } | null =
  null;

/**
 * Every lit-review digest in the vault, keyed by the paper it reviewed.
 *
 * The scheduled research team enqueues papers with no `item_id`, so those
 * digests never produce a `review_completed` event and the bibliography has no
 * record of them. Deriving the link from the digests themselves means a paper
 * filed from the CEO Brief still carries its review summary on /research, and
 * no second copy of that fact is written anywhere to drift.
 */
function digestIndex(): Map<string, string> {
  let names: string[];
  try {
    names = readdirSync(DIGEST_DIR)
      .filter((name) => name.endsWith(".md"))
      .sort()
      .reverse();
  } catch {
    return new Map();
  }
  let signature: string;
  try {
    signature = `${names.length}:${statSync(DIGEST_DIR).mtimeMs}`;
  } catch {
    signature = `${names.length}:unknown`;
  }
  if (digestCache?.signature === signature) return digestCache.byIdentity;

  const byIdentity = new Map<string, string>();
  // Newest first, and an existing key is never overwritten: a re-reviewed
  // paper links to its most recent digest.
  for (const name of names) {
    let raw = "";
    try {
      raw = readFileSync(path.join(DIGEST_DIR, name), "utf8");
    } catch {
      continue;
    }
    const { fm } = parseFrontmatter(raw);
    if ((fm.type ?? "").toLowerCase() !== "lit-review") continue;
    const relPath = `${DIGEST_REL}/${name}`;
    for (const key of identityKeys({ url: fm.url, paperId: fm.paper_id })) {
      if (!byIdentity.has(key)) byIdentity.set(key, relPath);
    }
  }
  digestCache = { signature, byIdentity };
  return byIdentity;
}

function withDigestLinks(items: BibliographyItem[]): BibliographyItem[] {
  const digests = digestIndex();
  if (!digests.size) return items;
  return items.map((item) => {
    if (item.digestPath) return item;
    const derived = identityKeys({
      url: item.url,
      doi: item.doi,
      paperId: item.preprintDoi,
    })
      .map((key) => digests.get(key))
      .find(Boolean);
    return derived ? { ...item, digestPath: derived } : item;
  });
}

export async function listBibliography(
  target?: ResearchTarget,
): Promise<BibliographyItem[]> {
  const items = withDigestLinks(foldBibliography());
  return target
    ? items.filter((item) =>
        target.type === "project"
      ? item.projects.some((project) => project.id === target.id)
          : target.type === "resource"
            ? item.resources.some((resource) => resource.id === target.id)
            : item.areas.some((area) => area.id === target.id),
      )
    : items;
}

/**
 * Where one bibliography entry currently sits, as the picker value and the
 * label shown beside it. One definition, used by /research and by the CEO
 * Brief's save control, so the two surfaces cannot disagree about where a paper
 * is filed.
 */
export function describeResearchTarget(
  item: Pick<BibliographyItem, "projects" | "resources" | "areas">,
  brainstormedResourceIds: Set<string>,
): { targetValue: string; targetLabel: string } {
  const project = item.projects[0];
  if (project) {
    return {
      targetValue: `project:${project.id}`,
      targetLabel: `Project · ${project.title}`,
    };
  }
  const resource = item.resources[0];
  // A paper's own Brainstorming resource is "unfiled", not a destination the owner
  // chose, so it reads as Brainstorming rather than as itself.
  if (resource && !brainstormedResourceIds.has(resource.id)) {
    return {
      targetValue: `resource:${resource.id}`,
      targetLabel: `Resource · ${resource.title}`,
    };
  }
  const area = resource ? undefined : item.areas[0];
  // Legacy rows: papers filed before Brainstorming became a resource domain.
  if (area && area.title.toLowerCase() !== "brainstorming") {
    return {
      targetValue: `area:${area.id}`,
      targetLabel: `Area · ${area.title}`,
    };
  }
  return {
    targetValue: "brainstorming",
    targetLabel: "Brainstorming · unfiled",
  };
}

/** Resource rows that are papers parked in Brainstorming, not destinations. */
export async function getBrainstormedResourceIds(): Promise<Set<string>> {
  const areaId = await getBrainstormingAreaId();
  if (!areaId) return new Set();
  const rows = await db.resource.findMany({
    where: { areaId },
    select: { id: true },
  });
  return new Set(rows.map((row) => row.id));
}

export type DigestLibraryEntry = {
  itemId: string;
  targetValue: string;
  targetLabel: string;
};

/**
 * Digest path -> its bibliography entry, for digests already in the library.
 *
 * The CEO Brief uses it to say where a report is filed instead of offering to
 * file it again.
 */
export async function getDigestLibraryIndex(): Promise<
  Record<string, DigestLibraryEntry>
> {
  const linked = (await listBibliography()).filter((item) => item.digestPath);
  if (!linked.length) return {};
  const brainstormed = await getBrainstormedResourceIds();
  const index: Record<string, DigestLibraryEntry> = {};
  for (const item of linked) {
    index[item.digestPath as string] = {
      itemId: item.itemId,
      ...describeResearchTarget(item, brainstormed),
    };
  }
  return index;
}

export type ResearchDigestEntry = {
  /** Vault-relative path under Memory/, for the /vault reader. */
  relPath: string;
  fileName: string;
  date: string;
  title: string;
  relevance: string;
  reviewFormat: string;
  /** The verdict rationale — the one line the owner is guaranteed to read. */
  verdict: string;
};

/**
 * Every research digest on disk, newest first, for the /research/digests page.
 *
 * Reads the same files digestIndex() does but keeps them all (not only the
 * lit-reviews with an identity key): the daily paper digest and any legacy
 * format still deserve a row. The verdict is the first blockquote's rationale,
 * the same convention executive-digest.ts reads.
 */
export async function listResearchDigests(
  limit = 60,
): Promise<ResearchDigestEntry[]> {
  let names: string[];
  try {
    names = readdirSync(DIGEST_DIR)
      .filter((name) => name.endsWith(".md"))
      .sort()
      .reverse();
  } catch {
    return [];
  }
  const out: ResearchDigestEntry[] = [];
  for (const name of names.slice(0, Math.max(1, Math.min(limit, 200)))) {
    let raw = "";
    try {
      raw = readFileSync(path.join(DIGEST_DIR, name), "utf8");
    } catch {
      continue;
    }
    const { fm, body } = parseFrontmatter(raw);
    const heading = body.match(/^#\s+(.+)$/m)?.[1]?.trim() ?? "";
    const quote = body.match(/(?:^|\n)((?:[ \t]*>[^\n]*\n?)+)/)?.[1] ?? "";
    const verdict = quote
      .split(/\r?\n/)
      .map((line) => line.replace(/^[ \t]*>[ \t]?/, "").trim())
      .filter(
        (line) =>
          line &&
          !/^\*\*(?:VERDICT|EVIDENCE GAP)\b/i.test(line) &&
          !/^\*\*Next action:/i.test(line),
      )
      .join(" ")
      .replace(/\*\*/g, "")
      .trim();
    out.push({
      relPath: `${DIGEST_REL}/${name}`,
      fileName: name,
      date: name.match(/^(\d{4}-\d{2}-\d{2})/)?.[1] ?? fm.date ?? "",
      title: fm.title || heading || name.replace(/\.md$/, ""),
      relevance: (fm.relevance ?? "").toLowerCase(),
      reviewFormat: (fm.review_format ?? "").toLowerCase(),
      verdict,
    });
  }
  return out;
}

export async function listRecentResearchReviews(limit = 20) {
  const jobs = await listJobs({ kind: "research.lit_review" });
  return Promise.all(
    jobs
      .slice(-Math.max(1, Math.min(limit, 50)))
      .reverse()
      .map((job) => getResearchReviewStatus(job.job)),
  ).then((rows) => rows.filter((row): row is ResearchReviewStatus => Boolean(row)));
}

function issued(value: string): { "date-parts": number[][] } | undefined {
  const parts = value
    .slice(0, 10)
    .split("-")
    .map(Number)
    .filter(Number.isFinite);
  return parts.length ? { "date-parts": [parts] } : undefined;
}

export async function bibliographyAsCsl(target: ResearchTarget) {
  return (await listBibliography(target)).map((item) => ({
    id: item.itemId,
    type: "article-journal",
    title: item.title,
    author: item.authors,
    issued: issued(item.publishedAt),
    "container-title": item.journal || undefined,
    DOI: item.doi || item.preprintDoi || undefined,
    URL: item.url || undefined,
    abstract: item.abstract || undefined,
    keyword: [
      ...item.projects.flatMap((project) => [
        `project:${project.id}`,
        `project-title:${project.title}`,
      ]),
      ...item.resources.flatMap((resource) => [
        `resource:${resource.id}`,
        `resource-title:${resource.title}`,
      ]),
      ...item.areas.flatMap((area) => [
        `area:${area.id}`,
        `area-title:${area.title}`,
      ]),
      "rho-reviewed",
      item.source ? `source:${item.source}` : "",
    ].filter(Boolean),
  }));
}
