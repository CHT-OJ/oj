import assert from "node:assert/strict";
import test from "node:test";

import { ResolverSession } from "../core.js";
import { ResolutionPlanner } from "../planner.js";
import { ResolutionPlayer } from "../player.js";
import { RowSweepPolicy, selectRowSweepTarget } from "../policies.js";
import {
  ICPC_EVENT_DELAYS_MS,
  RESOLUTION_STEP_TYPES,
  effectiveDelay,
  usesSingleStepTiming,
} from "../timing.js";
import { icpcPayload } from "./fixtures.js";
import { defaultPayload } from "./fixtures.js";

function problem(id, order) {
  return {
    id,
    code: id,
    label: id,
    name: `Problem ${id}`,
    order,
    max_score: 1,
    first_solve_participation_id: null,
    final_total_ac: 0,
  };
}

function icpcCell(problemId, points, time, tries, frozenPoints, frozenTries, pending) {
  return {
    problem_id: problemId,
    attempted: true,
    final: { points, time, tries },
    frozen: { points: frozenPoints, time, tries: frozenTries, pending },
  };
}

function contestant(id, problems, order) {
  return {
    participation_id: id,
    profile_id: id + 100,
    username: `team-${id}`,
    display_name: `Team ${id}`,
    full_name: "",
    user_css_class: "rating rate-none user",
    profile_url: `/user/team-${id}`,
    avatar_url: null,
    rank_logo_url: null,
    organizations: [],
    is_disqualified: false,
    submission_count: 0,
    final_order: order,
    frozen_order: order,
    final: { score: 0, cumtime: 0, tiebreaker: 0 },
    frozen: { score: 0, cumtime: 0, tiebreaker: 0 },
    problems,
  };
}

function rowSweepPayload() {
  const problems = [problem("A", 0), problem("B", 1), problem("C", 2), problem("D", 3)];
  const contestants = [];
  for (let id = 1; id <= 4; id += 1) {
    contestants.push(
      contestant(
        id,
        {
          A: icpcCell("A", 1, id * 60, 1, 1, 1, false),
          B: icpcCell("B", 1, (id + 4) * 60, 1, 1, 1, false),
        },
        id - 1,
      ),
    );
  }
  for (let id = 5; id <= 9; id += 1) {
    const cells = {
      A: icpcCell("A", 1, (id - 4) * 600, 1, 1, 1, false),
    };
    if (id === 9) {
      cells.D = icpcCell("D", 0, 3600, 1, 0, 1, true);
    }
    contestants.push(contestant(id, cells, id - 1));
  }
  contestants.push(
    contestant(
      10,
      {
        B: icpcCell("B", 1, 300, 1, 0, 1, true),
        C: icpcCell("C", 1, 420, 1, 0, 1, true),
      },
      9,
    ),
  );
  return {
    schema_version: 1,
    contest: {
      id: 9,
      key: "row-sweep",
      name: "Row sweep",
      format: "icpc",
      format_config: { penalty: 20 },
      rank_display_options: 3,
      points_precision: 3,
      frozen_last_minutes: 60,
      official_freeze_available: true,
    },
    problems,
    contestants,
  };
}

function sameRowPayload() {
  const problems = [
    { ...problem("A", 0), max_score: 100 },
    { ...problem("B", 1), max_score: 100 },
  ];
  const defaultCell = (problemId, points, time) => ({
    problem_id: problemId,
    attempted: true,
    final: { points, time },
    frozen: null,
  });
  const contestants = [1, 2, 3].map((id, index) => ({
    ...contestant(
      id,
      id === 3 ? { A: defaultCell("A", 0, 30), B: defaultCell("B", 100, 60) } : {},
      index,
    ),
    final:
      id === 3
        ? { score: 100, cumtime: 60, tiebreaker: 0 }
        : { score: 0, cumtime: 0, tiebreaker: 0 },
    frozen: null,
  }));
  return {
    schema_version: 1,
    contest: {
      id: 10,
      key: "same-row",
      name: "Same row",
      format: "default",
      format_config: {},
      rank_display_options: 3,
      points_precision: 3,
      frozen_last_minutes: 0,
      official_freeze_available: false,
    },
    problems,
    contestants,
  };
}

function createPlayer({ speed = 1, waits = [], steps = [], wait = null } = {}) {
  const session = new ResolverSession(icpcPayload, {
    baseline: "official-freeze",
    tieOrder: "seeded",
  });
  const policy = new RowSweepPolicy(icpcPayload.problems.map((entry) => entry.id));
  const planner = new ResolutionPlanner({
    payload: icpcPayload,
    targetSelector: (currentSession) => policy.select(currentSession),
    singleStepStartRank: 1,
    awardPlaces: 0,
    hardPauses: { singleStep: true, award: false, firstSolve: true },
  });
  const player = new ResolutionPlayer({
    session,
    planner,
    playbackSpeed: speed,
    wait: wait ?? (async (duration) => waits.push(duration)),
    onStep: async (step) => steps.push(step.type),
  });
  return { session, player };
}

test("ICPC row sweep stays on row 10 after its occupant moves from #10 to #5", () => {
  const payload = rowSweepPayload();
  const session = new ResolverSession(payload, {
    baseline: "official-freeze",
    tieOrder: "seeded",
  });
  const policy = new RowSweepPolicy(payload.problems.map((entry) => entry.id));

  const first = policy.select(session);
  assert.deepEqual(first, { contestantId: 10, problemId: "B" });
  const transition = session.revealCell(first.contestantId, first.problemId);
  assert.equal(transition.effects.positionBefore, 10);
  assert.equal(transition.effects.positionAfter, 5);

  const second = policy.select(session);
  assert.deepEqual(second, { contestantId: 9, problemId: "D" });
  assert.notEqual(second.contestantId, 10);
  assert.equal(
    session.getState().standings.at(-1).contestantId,
    9,
    "the new row-10 occupant is selected immediately",
  );
});

test("same-row result keeps the contestant eligible for its next leftmost cell", () => {
  const payload = sameRowPayload();
  const session = new ResolverSession(payload, { baseline: "beginning", tieOrder: "source" });
  const policy = new RowSweepPolicy(payload.problems.map((entry) => entry.id));
  const first = policy.select(session);
  assert.deepEqual(first, { contestantId: 3, problemId: "A" });
  const transition = session.revealCell(first.contestantId, first.problemId);
  assert.equal(transition.effects.positionAfter, transition.effects.positionBefore);
  assert.deepEqual(policy.select(session), { contestantId: 3, problemId: "B" });
});

test("row-sweep selection is bottom-most first and leftmost within that contestant", () => {
  const standings = [{ contestantId: 1 }, { contestantId: 2 }, { contestantId: 3 }];
  const cells = [
    { contestantId: 1, problemId: "A" },
    { contestantId: 3, problemId: "C" },
    { contestantId: 3, problemId: "B" },
  ];
  assert.deepEqual(selectRowSweepTarget(standings, cells, ["A", "B", "C"]), {
    contestantId: 3,
    problemId: "B",
  });
});

test("predetermined choice only overrides problem order inside the lowest contestant", () => {
  const standings = [{ contestantId: 1 }, { contestantId: 2 }, { contestantId: 3 }];
  const cells = [
    { contestantId: 1, problemId: "C" },
    { contestantId: 3, problemId: "A" },
    { contestantId: 3, problemId: "B" },
  ];
  assert.deepEqual(selectRowSweepTarget(standings, cells, ["A", "B", "C"], { 1: "C", 3: "B" }), {
    contestantId: 3,
    problemId: "B",
  });
  assert.deepEqual(selectRowSweepTarget(standings, cells, ["A", "B", "C"], { 3: "missing" }), {
    contestantId: 3,
    problemId: "A",
  });
});

test("official ICPC event delays and playback speed scaling are exact", () => {
  assert.deepEqual(ICPC_EVENT_DELAYS_MS, {
    SELECT_TEAM: 1300,
    SELECT_PROBLEM: 1000,
    RESULT_MOVE: 2250,
    RESULT_STAY: 1500,
    RESULT_FAILED: 850,
    DESELECT: 250,
    SELECT_SUBMISSION: 450,
  });
  assert.equal(effectiveDelay(2250, 2), 1125);
  assert.equal(effectiveDelay(2250, 0.5), 4500);
});

test("singleStepStartRank is one-based: rank 7 auto, rank 6 single-step", () => {
  assert.equal(usesSingleStepTiming(7, 6), false);
  assert.equal(usesSingleStepTiming(6, 6), true);
});

test("SingleStepTiming pauses after team, problem, and result but not deselection", () => {
  const session = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    tieOrder: "source",
  });
  const policy = new RowSweepPolicy(defaultPayload.problems.map((entry) => entry.id));
  const planner = new ResolutionPlanner({
    payload: defaultPayload,
    targetSelector: (currentSession) => policy.select(currentSession),
    singleStepStartRank: 1,
    awardPlaces: 0,
  });
  const plan = planner.planNext(session);
  assert.equal(plan.timing, "single-step");
  assert.deepEqual(
    plan.steps.filter((step) => step.type === RESOLUTION_STEP_TYPES.PAUSE).map((step) => step.kind),
    ["single-step-team", "single-step-problem", "single-step-result"],
  );
  const deselectIndex = plan.steps.findIndex(
    (step) => step.type === RESOLUTION_STEP_TYPES.DESELECT,
  );
  assert.equal(
    plan.steps.slice(deselectIndex + 1).some((step) => step.type === RESOLUTION_STEP_TYPES.PAUSE),
    false,
  );
});

test("Rewind clears a selection-only SingleStep pause before any reveal", async () => {
  const session = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    tieOrder: "source",
  });
  const policy = new RowSweepPolicy(defaultPayload.problems.map((entry) => entry.id));
  const planner = new ResolutionPlanner({
    payload: defaultPayload,
    targetSelector: (currentSession) => policy.select(currentSession),
    singleStepStartRank: 1,
    awardPlaces: 0,
  });
  const player = new ResolutionPlayer({ session, planner });

  const result = await player.fastForwardToNextPause();
  assert.equal(result.pause.kind, "single-step-team");
  assert.equal(session.getHistory().cursor, 0);
  assert.notEqual(player.getState().presentation.selectedContestantId, null);

  await player.rewindToPreviousPause();
  assert.deepEqual(player.getState().presentation, {
    selectedContestantId: null,
    selectedProblemId: null,
    resultType: null,
  });
  assert.equal(player.getState().checkpointIndex, 0);
  assert.equal(session.getHistory().cursor, 0);
});

test("Forward executes intermediate actions and delays until the next hard PauseStep", async () => {
  const waits = [];
  const steps = [];
  const { session, player } = createPlayer({ waits, steps });
  const result = await player.playToNextPause(true);

  assert.equal(result.pause.type, RESOLUTION_STEP_TYPES.PAUSE);
  assert.equal(result.pause.kind, "first-solve");
  assert.equal(session.getHistory().cursor, 2);
  assert.deepEqual(waits, [1300, 1000, 850, 250, 1300, 1000, 1500]);
  assert.equal(steps.includes(RESOLUTION_STEP_TYPES.SELECT_TEAM), true);
  assert.equal(steps.includes(RESOLUTION_STEP_TYPES.SELECT_PROBLEM), true);
  assert.equal(steps.filter((type) => type === RESOLUTION_STEP_TYPES.REVEAL_CELL).length, 2);
});

test("Fast Forward reaches the same semantic pause state without narrative delays", async () => {
  const forward = createPlayer();
  await forward.player.playToNextPause(true);
  const expected = forward.session.getState();

  const waits = [];
  const fast = createPlayer({ waits });
  const result = await fast.player.fastForwardToNextPause();
  assert.equal(result.pause.kind, "first-solve");
  assert.deepEqual(fast.session.getState(), expected);
  assert.deepEqual(waits, []);
});

test("Rewind restores the exact previous semantic pause state", async () => {
  const { session, player } = createPlayer();
  const baseline = session.getState();
  await player.fastForwardToNextPause();
  assert.equal(session.getHistory().cursor, 2);
  await player.rewindToPreviousPause();
  assert.deepEqual(session.getState(), baseline);
  assert.equal(session.getHistory().cursor, 0);
});

test("Reset and replay are deterministic", async () => {
  const { session, player } = createPlayer();
  const baseline = session.getState();
  await player.fastForwardToNextPause();
  const firstRun = session.getState();
  await player.resetToBeginning();
  assert.deepEqual(session.getState(), baseline);
  await player.fastForwardToNextPause();
  assert.deepEqual(session.getState(), firstRun);
});

test("row-sweep selection remains pure when called repeatedly during render", () => {
  const session = new ResolverSession(icpcPayload, { baseline: "official-freeze" });
  const policy = new RowSweepPolicy(icpcPayload.problems.map((entry) => entry.id));
  const historyBefore = session.getHistory();
  const first = policy.select(session);
  const second = policy.select(session);
  assert.deepEqual(second, first);
  assert.deepEqual(session.getHistory(), historyBefore);
});

test("operator projection simulates the next reveal without mutating live state", () => {
  const payload = rowSweepPayload();
  const session = new ResolverSession(payload, {
    baseline: "official-freeze",
    tieOrder: "seeded",
  });
  const policy = new RowSweepPolicy(payload.problems.map((entry) => entry.id));
  const planner = new ResolutionPlanner({
    payload,
    targetSelector: (currentSession) => policy.select(currentSession),
    singleStepStartRank: 6,
    awardPlaces: 6,
  });
  const stateBefore = session.getState();
  const historyBefore = session.getHistory();
  const projection = planner.projectNext(session);
  assert.deepEqual(
    {
      currentPosition: projection.currentPosition,
      actualPositionAfterReveal: projection.actualPositionAfterReveal,
      movementDelta: projection.movementDelta,
      remainingUnresolvedCells: projection.remainingUnresolvedCells,
    },
    {
      currentPosition: 10,
      actualPositionAfterReveal: 5,
      movementDelta: 5,
      remainingUnresolvedCells: 2,
    },
  );
  assert.deepEqual(session.getState(), stateBefore);
  assert.deepEqual(session.getHistory(), historyBefore);
});

test("cancelling playback prevents overlapping asynchronous reveal chains", async () => {
  let releaseDelay;
  let signalDelayStarted;
  const delayStarted = new Promise((resolve) => {
    signalDelayStarted = resolve;
  });
  const wait = () =>
    new Promise((resolve) => {
      releaseDelay = resolve;
      signalDelayStarted();
    });
  const { session, player } = createPlayer({ wait });
  const run = player.playToNextPause(true);
  await delayStarted;
  player.cancel("Operator pause.");
  releaseDelay();
  await run;
  assert.equal(session.getHistory().cursor, 0);
  assert.equal(player.getState().running, false);
});
