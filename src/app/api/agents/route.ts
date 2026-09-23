import { NextResponse } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { authorizeOps } from "@/lib/auth";

const REPO = process.cwd();
const STATE = path.join(
  REPO,
  ".claude",
  "data",
  "state",
  "agent-deploy-state.json",
);
const PYTHON =
  process.env.SECONDBRAIN_PYTHON ||
  "python";

type DeployState = {
  runId?: string;
  status: "idle" | "running" | "completed" | "failed";
  startedAt?: string | null;
  finishedAt?: string | null;
  exitCode?: number | null;
  output?: string;
  queue?: Record<string, number>;
};

async function readState(): Promise<DeployState> {
  try {
    const parsed = JSON.parse(await fs.readFile(STATE, "utf8")) as DeployState;
    if (!parsed?.status) return { status: "idle" };
    if (
      parsed.status === "running" &&
      parsed.startedAt &&
      Date.now() - Date.parse(parsed.startedAt) > 4 * 60 * 60 * 1000
    ) {
      return {
        ...parsed,
        status: "failed",
        output: "The tracked run exceeded four hours and is considered stale.",
      };
    }
    return parsed;
  } catch {
    return { status: "idle" };
  }
}

export async function GET() {
  return NextResponse.json(await readState());
}

export async function POST(req: Request) {
  const auth = authorizeOps(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.message }, { status: auth.status });
  }
  const body = await req.json().catch(() => ({}));
  if (body.action !== "deploy-all") {
    return NextResponse.json({ error: "unknown action" }, { status: 400 });
  }
  const current = await readState();
  if (current.status === "running") {
    return NextResponse.json(
      { error: "All agents are already deployed.", state: current },
      { status: 409 },
    );
  }

  await fs.mkdir(path.dirname(STATE), { recursive: true });
  await fs.writeFile(
    STATE,
    JSON.stringify({
      status: "running",
      startedAt: new Date().toISOString(),
      finishedAt: null,
      output: "Starting all enabled teams...",
    }),
    "utf8",
  );
  const child = spawn(PYTHON, [".claude/scripts/agent_deploy.py"], {
    cwd: REPO,
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  child.on("error", (error) => {
    void fs.writeFile(
      STATE,
      JSON.stringify({
        status: "failed",
        startedAt: new Date().toISOString(),
        finishedAt: new Date().toISOString(),
        output: String(error),
      }),
      "utf8",
    );
  });
  child.unref();
  return NextResponse.json({ ok: true, status: "starting" }, { status: 202 });
}
