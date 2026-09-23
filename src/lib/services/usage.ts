import { promises as fs } from "fs";
import path from "path";

/**
 * API usage ledger reader. Reads the append-only ledger written by
 * .claude/scripts/usage_ledger.py (one JSON object per line) and aggregates
 * month-to-date spend by provider and model for the dashboard usage panel.
 *
 * Read-only, framework-free (filesystem, no Prisma). No secrets touched -
 * the ledger holds only token counts and dollar amounts.
 */

const LEDGER = path.join(process.cwd(), ".claude", "data", "usage.jsonl");

/** Soft monthly budget (USD) for the progress bar; override via env. */
const MONTHLY_BUDGET = Number(process.env.SECONDBRAIN_USAGE_BUDGET ?? 50);

export interface UsageRow {
  ts: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens?: number;
  cost_usd: number;
  source: string;
}

export interface UsageBucket {
  key: string;
  calls: number;
  tokens: number;
  cost: number;
}

export interface UsageSummary {
  hasData: boolean;
  month: string; // YYYY-MM
  totalCost: number;
  totalTokens: number;
  budget: number;
  byProvider: UsageBucket[];
  byModel: UsageBucket[];
  bySource: UsageBucket[];
}

const PROVIDER_LABEL: Record<string, string> = {
  claude: "Claude",
  openai: "ChatGPT",
  google: "Gemini",
  other: "Other",
};

export function providerLabel(p: string): string {
  return PROVIDER_LABEL[p] ?? p;
}

function bump(map: Map<string, UsageBucket>, key: string, tokens: number, cost: number) {
  const b = map.get(key) ?? { key, calls: 0, tokens: 0, cost: 0 };
  b.calls += 1;
  b.tokens += tokens;
  b.cost += cost;
  map.set(key, b);
}

const sortByCost = (a: UsageBucket, b: UsageBucket) => b.cost - a.cost;

export async function getUsageSummary(): Promise<UsageSummary> {
  const month = new Date().toISOString().slice(0, 7);
  const empty: UsageSummary = {
    hasData: false,
    month,
    totalCost: 0,
    totalTokens: 0,
    budget: MONTHLY_BUDGET,
    byProvider: [],
    byModel: [],
    bySource: [],
  };

  let raw: string;
  try {
    raw = await fs.readFile(LEDGER, "utf-8");
  } catch {
    return empty;
  }

  const providers = new Map<string, UsageBucket>();
  const models = new Map<string, UsageBucket>();
  const sources = new Map<string, UsageBucket>();
  let totalCost = 0;
  let totalTokens = 0;
  let seen = 0;

  for (const line of raw.split(/\r?\n/)) {
    const t = line.trim();
    if (!t) continue;
    let r: UsageRow;
    try {
      r = JSON.parse(t);
    } catch {
      continue;
    }
    if (!String(r.ts ?? "").startsWith(month)) continue; // month-to-date only
    const tokens = (r.input_tokens ?? 0) + (r.output_tokens ?? 0);
    const cost = Number(r.cost_usd ?? 0);
    seen += 1;
    totalCost += cost;
    totalTokens += tokens;
    bump(providers, r.provider ?? "other", tokens, cost);
    bump(models, r.model ?? "unknown", tokens, cost);
    bump(sources, r.source ?? "unknown", tokens, cost);
  }

  if (seen === 0) return empty;

  return {
    hasData: true,
    month,
    totalCost,
    totalTokens,
    budget: MONTHLY_BUDGET,
    byProvider: [...providers.values()].sort(sortByCost),
    byModel: [...models.values()].sort(sortByCost),
    bySource: [...sources.values()].sort(sortByCost),
  };
}
