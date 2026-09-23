import { promises as fs } from "fs";
import path from "path";

/**
 * Second Brain agent-layer bridge: reads the vault + agent state from disk so
 * the dashboard can surface drafts, paper digests, and heartbeat status.
 * Read-only and framework-free (all filesystem, no Prisma).
 *
 * Security: only reads under VAULT/Memory/ and .claude/data/state/. Finance/
 * and Personal/ are never touched here - the browser is scoped to Memory/.
 */

const REPO = process.cwd();
const MEMORY = path.join(REPO, "VAULT", "Memory");
const STATE = path.join(REPO, ".claude", "data", "state");

export type DraftStatus = "active" | "sent" | "expired";

export interface Draft {
  filename: string;
  status: DraftStatus;
  type: string;
  recipient: string;
  subject: string;
  context: string;
  created: string;
  originalMessage: string;
  draftReply: string;
  relationshipGroup: string;
  relationshipStatus: "inferred" | "confirmed";
  relationshipRationale: string;
  relationshipConfidence: string;
  replyEdited: boolean;
}

/** Minimal YAML-frontmatter parser (flat key: value only) + body split. */
export function parseFrontmatter(raw: string): { fm: Record<string, string>; body: string } {
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!m) return { fm: {}, body: raw };
  const fm: Record<string, string> = {};
  for (const line of m[1].split(/\r?\n/)) {
    const i = line.indexOf(":");
    if (i > 0) fm[line.slice(0, i).trim()] = line.slice(i + 1).trim().replace(/^["']|["']$/g, "");
  }
  return { fm, body: m[2] };
}

function section(body: string, heading: string): string {
  const re = new RegExp(`##\\s+${heading}\\s*\\r?\\n([\\s\\S]*?)(?=\\r?\\n##\\s|$)`, "i");
  return body.match(re)?.[1].trim() ?? "";
}

async function readDir(dir: string): Promise<string[]> {
  try {
    return (await fs.readdir(dir))
      .filter((f) => f.endsWith(".md") && f !== "index.md") // skip the vault-map files
      .sort()
      .reverse();
  } catch {
    return [];
  }
}

export async function listDrafts(status: DraftStatus = "active"): Promise<Draft[]> {
  const dir = path.join(MEMORY, "drafts", status);
  const files = await readDir(dir);
  const out: Draft[] = [];
  for (const filename of files) {
    const raw = await fs.readFile(path.join(dir, filename), "utf-8").catch(() => "");
    if (!raw) continue;
    const { fm, body } = parseFrontmatter(raw);
    out.push({
      filename,
      status,
      type: fm.type ?? "email",
      recipient: fm.recipient ?? "",
      subject: fm.subject ?? "",
      context: fm.context ?? "",
      created: fm.created ?? "",
      originalMessage: section(body, "Original Message"),
      draftReply: section(body, "Draft Reply"),
      relationshipGroup: fm.relationship_group ?? "Collaborator",
      relationshipStatus:
        fm.relationship_status === "confirmed" ? "confirmed" : "inferred",
      relationshipRationale: fm.relationship_rationale ?? "",
      relationshipConfidence: fm.relationship_confidence ?? "low",
      replyEdited: fm.reply_edited === "true",
    });
  }
  return out;
}

export interface HeartbeatStatus {
  lastRun: string | null;
  papersDate: string | null;
  running: boolean; // whether state exists at all
}

export async function getHeartbeatStatus(): Promise<HeartbeatStatus> {
  try {
    const raw = await fs.readFile(path.join(STATE, "heartbeat-state.json"), "utf-8");
    const s = JSON.parse(raw);
    return { lastRun: s.last_run ?? null, papersDate: s.papers_date ?? null, running: true };
  } catch {
    return { lastRun: null, papersDate: null, running: false };
  }
}

export interface DigestFile {
  filename: string;
  date: string;
  preview: string;
}

export async function listPaperDigests(limit = 10): Promise<DigestFile[]> {
  const dir = path.join(MEMORY, "research");
  const files = (await readDir(dir)).slice(0, limit);
  const out: DigestFile[] = [];
  for (const filename of files) {
    const raw = await fs.readFile(path.join(dir, filename), "utf-8").catch(() => "");
    const { fm, body } = parseFrontmatter(raw);
    out.push({
      filename,
      date: fm.date ?? filename.slice(0, 10),
      preview: body.replace(/^#.*$/m, "").replace(/[#*_`>]/g, "").trim().slice(0, 200),
    });
  }
  return out;
}

/** ---- Vault browser (scoped to VAULT/Memory/, path-traversal safe) ---- */

export interface VaultEntry {
  name: string;
  isDir: boolean;
  relPath: string;
}

function resolveInMemory(relPath: string): string | null {
  const clean = (relPath || "").replace(/\\/g, "/").replace(/^\/+/, "");
  const abs = path.resolve(MEMORY, clean);
  const root = path.resolve(MEMORY);
  // must stay within MEMORY (blocks ../ traversal, and thus Finance/Personal)
  if (abs !== root && !abs.startsWith(root + path.sep)) return null;
  return abs;
}

export async function listVault(relPath = ""): Promise<VaultEntry[] | null> {
  const abs = resolveInMemory(relPath);
  if (!abs) return null;
  try {
    const entries = await fs.readdir(abs, { withFileTypes: true });
    return entries
      .filter((e) => !e.name.startsWith(".") && e.name !== "BOOTSTRAP.md")
      .map((e) => ({
        name: e.name,
        isDir: e.isDirectory(),
        relPath: path.posix.join(relPath.replace(/\\/g, "/"), e.name),
      }))
      .sort((a, b) => (a.isDir === b.isDir ? a.name.localeCompare(b.name) : a.isDir ? -1 : 1));
  } catch {
    return null;
  }
}

export async function readVaultFile(relPath: string): Promise<string | null> {
  const abs = resolveInMemory(relPath);
  if (!abs || !abs.endsWith(".md")) return null;
  return fs.readFile(abs, "utf-8").catch(() => null);
}
