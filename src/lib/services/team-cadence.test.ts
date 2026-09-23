import assert from "node:assert/strict";
import { test } from "node:test";
import { cadenceStatus } from "./team-cadence";

const NOW = new Date("2026-09-22T12:00:00-07:00");

test("daily and manual teams are not judged", () => {
  assert.equal(cadenceStatus("daily", [], NOW), null);
  assert.equal(cadenceStatus("manual", [], NOW), null);
});

test("a weekly team that never succeeded is overdue", () => {
  const s = cadenceStatus("weekly", [
    { status: "failed", created_ts: "2026-09-21T21:30:16-07:00" },
  ], NOW);
  assert.deepEqual(s, { lastSuccessIso: null, overdue: true });
});

test("last week's successful run is on time", () => {
  const s = cadenceStatus("weekly", [
    { status: "approved", created_ts: "2026-09-21T21:30:16-07:00" },
    { status: "failed", created_ts: "2026-09-21T21:30:16-07:00" },
  ], NOW);
  assert.equal(s?.overdue, false);
  assert.equal(s?.lastSuccessIso, "2026-09-21T21:30:16-07:00");
});

test("a skipped week makes the team overdue", () => {
  // 2026-09-14 never ran and 2026-09-07 failed: last success was 2026-08-24.
  const s = cadenceStatus("weekly", [
    { status: "approved", created_ts: "2026-08-24T21:00:14-07:00" },
    { status: "failed", created_ts: "2026-09-07T21:00:17-07:00" },
  ], new Date("2026-09-15T09:00:00-07:00"));
  assert.equal(s?.overdue, true);
  assert.equal(s?.lastSuccessIso, "2026-08-24T21:00:14-07:00");
});

test("a run awaiting review counts as done", () => {
  const s = cadenceStatus("weekly", [
    { status: "needs_review", created_ts: "2026-09-21T21:30:16-07:00" },
  ], NOW);
  assert.equal(s?.overdue, false);
});

test("a run whose findings they rejected still happened", () => {
  const s = cadenceStatus("weekly", [
    { status: "rejected", created_ts: "2026-09-21T21:30:16-07:00" },
  ], NOW);
  assert.equal(s?.overdue, false);
});

test("a machine that has never run the team is not overdue", () => {
  assert.deepEqual(cadenceStatus("weekly", [], NOW), {
    lastSuccessIso: null,
    overdue: false,
  });
});
