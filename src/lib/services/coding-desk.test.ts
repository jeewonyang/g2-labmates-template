import assert from "node:assert/strict";
import { test } from "node:test";
import { summarizeCodingAgent, withCodingDesk } from "./coding-desk";
import type { G2AgentRun, G2AgentRunStatus } from "./g2-agent";
import type { TeamCard } from "./teams";

const NOW = Date.parse("2026-09-22T12:00:00Z");
const PERSONAS = {
  ledger: { name: "Ada", role: "Inbox" },
  coding: { name: "Cody", role: "Builds G2" },
};

function totals(partial: Partial<Record<G2AgentRunStatus, number>>): Record<G2AgentRunStatus, number> {
  return { queued: 0, running: 0, cancel_requested: 0, cancelled: 0, completed: 0, failed: 0, ...partial };
}

function run(status: G2AgentRunStatus, createdAt: string): G2AgentRun {
  return { id: createdAt, provider: "claude", prompt: "fix it", status, createdAt };
}

function card(id: string, over: Partial<TeamCard> = {}): TeamCard {
  return {
    id,
    name: id === "admin" ? "Admin" : id,
    summary: "",
    order: 0,
    enabled: true,
    cadence: "daily",
    run_at: null,
    producer: null,
    sensitivity_ceiling: "internal",
    kinds: ["draft.reply"],
    queued: 0,
    running: 0,
    needsReview: 0,
    failed: 0,
    completed: 0,
    lastRunIso: null,
    cadenceStatus: null,
    recentOutput: [],
    models: [],
    memberCards: [],
    ...over,
  };
}

test("done counts every finished run even when all were cleared off the monitor", () => {
  // The bug they reported: every finished run was dismissed, so the visible
  // list was empty and "done" read 0 after 22 fixes.
  const s = summarizeCodingAgent([], [], totals({ completed: 22, failed: 5 }));
  assert.equal(s.completed, 22);
  // A cleared failure no longer colours the desk red.
  assert.equal(s.failed, 0);
});

test("live and failed counts still come from the visible runs", () => {
  const s = summarizeCodingAgent(
    [run("running", "2026-09-22T11:00:00Z"), run("failed", "2026-09-22T10:00:00Z")],
    [],
    totals({ completed: 3, failed: 9, running: 1 }),
  );
  assert.equal(s.running, 1);
  assert.equal(s.failed, 1);
  assert.equal(s.completed, 3);
});

test("Cody joins the Admin room beside Ada and is counted once", () => {
  const s = summarizeCodingAgent(
    [run("queued", "2026-09-22T11:30:00Z")],
    [],
    totals({ completed: 22 }),
  );
  const cards = [
    card("admin", { needsReview: 2, queued: 1, completed: 40, lastRunIso: "2026-09-22T05:00:00Z" }),
    card("markets"),
  ];
  const out = withCodingDesk(cards, s, PERSONAS, NOW);

  assert.equal(out.length, 2, "no extra pod: Cody is a desk, not a card");
  const room = out[0];
  assert.deepEqual(room.memberCards.map((m) => m.name), ["Ada", "Cody"]);
  const [ada, cody] = room.memberCards;
  assert.equal(ada.needsReview, 2);
  assert.equal(ada.queued, 1);
  assert.equal(cody.desk, "coding");
  assert.equal(cody.stateOverride, "ready");
  // Room tallies = Ada's + Cody's, so the floor totals include Cody exactly once.
  assert.equal(room.queued, 2);
  assert.equal(room.completed, 62);
  assert.equal(room.needsReview, 2);
  assert.equal(room.lastRunIso, "2026-09-22T11:30:00Z");
  // Other cards untouched.
  assert.equal(out[1], cards[1]);
});

test("an idle Cody reports his last run instead of looking empty", () => {
  const s = summarizeCodingAgent(
    [{ ...run("completed", "2026-09-22T09:00:00Z"), finishedAt: "2026-09-22T10:00:00Z" }],
    [],
    totals({ completed: 1 }),
  );
  const cody = withCodingDesk([card("admin")], s, PERSONAS, NOW)[0].memberCards[1];
  assert.equal(cody.stateOverride, "idle");
  assert.equal(cody.statusNote, "last run 2h ago");
});
