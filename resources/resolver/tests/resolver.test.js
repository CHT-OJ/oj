import assert from "node:assert/strict";
import test from "node:test";

import {
  ResolverSession,
  UnsupportedResolverBaselineError,
  UnsupportedResolverFormatError,
} from "../core.js";
import { CEREMONY_PRESETS, SPEED_PRESETS, normalizeAwardPlaces } from "../controller.js";
import { rankContestants } from "../ranking.js";
import {
  BottomUpStickyPolicy,
  ByContestantPolicy,
  ByProblemPolicy,
  selectBottomUpStickyTarget,
  selectByContestantTarget,
  selectByProblemTarget,
} from "../policies.js";
import {
  deriveProblemStats,
  getCellPresentation,
  getOrganizationPresentation,
  normalizeRankDisplayOption,
} from "../presentation.js";
import { roundLikePython } from "../utils.js";
import {
  defaultPayload,
  icpcPayload,
  vnojLsoPayload,
  vnojNoPenaltyPayload,
  vnojPayload,
} from "./fixtures.js";

function getContestant(session, contestantId) {
  return session
    .getState()
    .contestants.find((contestant) => String(contestant.participationId) === String(contestantId));
}

function revealAll(session) {
  while (session.getResolvableCells().length) {
    const target = session.getResolvableCells()[0];
    session.revealCell(target.contestantId, target.problemId);
  }
}

function assertFinalParity(session, payload, expectedRanks, expectedOrder) {
  revealAll(session);
  const state = session.getState();

  payload.contestants.forEach((sourceContestant) => {
    const actual = state.contestants.find(
      (contestant) => contestant.participationId === sourceContestant.participation_id,
    );
    assert.deepEqual(
      {
        score: actual.score,
        cumtime: actual.cumtime,
        tiebreaker: actual.tiebreaker,
      },
      sourceContestant.final,
    );
  });

  Object.entries(expectedRanks).forEach(([contestantId, expectedRank]) => {
    const standing = state.standings.find(
      (entry) => String(entry.contestantId) === String(contestantId),
    );
    assert.equal(standing.rank, expectedRank);
  });

  if (expectedOrder) {
    assert.deepEqual(
      state.standings.map((standing) => standing.contestantId),
      expectedOrder,
    );
  }

  assert.deepEqual(
    deriveProblemStats(payload, state).map((stat) => stat.totalSolved),
    payload.problems.map((problem) => problem.final_total_ac),
  );
}

test("Default beginning baseline handles partial and zero scores without problem indexes", () => {
  const session = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    seed: "default-seed",
  });
  const initial = session.getState();
  assert.equal(
    initial.standings.every((standing) => standing.rank === 1),
    true,
  );
  assert.equal(session.getResolvableCells().length, 5);

  session.revealCell(11, 101);
  let contestant = getContestant(session, 11);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 100, cumtime: 100, tiebreaker: 0 },
  );

  session.revealCell(33, 101);
  contestant = getContestant(session, 33);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime },
    { score: 0, cumtime: 0 },
  );

  assertFinalParity(session, defaultPayload, { 11: 1, 22: 1, 33: 3 }, [22, 11, 33]);
  const tied = session.getState().standings.filter((standing) => standing.rank === 1);
  assert.equal(tied.length, 2);
});

test("ICPC official freeze preserves minutes, configured penalty, pending failures, and tied ranks", () => {
  const session = new ResolverSession(icpcPayload, {
    baseline: "official-freeze",
    seed: "icpc-seed",
  });
  assert.deepEqual(
    session.getState().standings.map((standing) => standing.contestantId),
    [303, 202, 101],
  );
  assert.deepEqual(session.getResolvableCells(), [
    { contestantId: 101, problemId: 42 },
    { contestantId: 101, problemId: 88 },
  ]);

  let contestant = getContestant(session, 101);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 1, cumtime: 10, tiebreaker: 10 },
  );

  session.revealCell(101, 42);
  contestant = getContestant(session, 101);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 1, cumtime: 10, tiebreaker: 10 },
  );

  session.revealCell(101, 88);
  contestant = getContestant(session, 101);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 2, cumtime: 85, tiebreaker: 60 },
  );

  assertFinalParity(session, icpcPayload, { 101: 3, 202: 1, 303: 1 });
  assert.deepEqual(
    session.getState().standings.map((standing) => standing.contestantId),
    [303, 202, 101],
  );
});

test("ICPC beginning baseline scores an AC after wrong tries independently of freeze", () => {
  const session = new ResolverSession(icpcPayload, { baseline: "beginning", seed: "icpc-full" });
  session.revealCell(101, 88);
  const contestant = getContestant(session, 101);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 1, cumtime: 75, tiebreaker: 60 },
  );
});

test("VNOJ official freeze uses pending counts and excludes zero-score penalties", () => {
  const session = new ResolverSession(vnojPayload, {
    baseline: "official-freeze",
    seed: "vnoj-seed",
  });
  assert.deepEqual(session.getResolvableCells(), [{ contestantId: 501, problemId: 9 }]);

  let contestant = getContestant(session, 501);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 50, cumtime: 600, tiebreaker: 300 },
  );

  const alreadyFull = getContestant(session, 503);
  assert.equal(alreadyFull.problems["9"].revealed, true);
  assert.equal(alreadyFull.problems["9"].pending, 0);

  session.revealCell(501, 9);
  contestant = getContestant(session, 501);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 100, cumtime: 1200, tiebreaker: 600 },
  );
  assertFinalParity(session, vnojPayload, { 501: 2, 502: 3, 503: 1 }, [503, 501, 502]);
});

test("VNOJ LSO true uses maximum score-altering time plus aggregate penalty", () => {
  const session = new ResolverSession(vnojLsoPayload, { baseline: "beginning", seed: "lso" });
  session.revealCell(601, 9);
  let contestant = getContestant(session, 601);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 50, cumtime: 400, tiebreaker: 100 },
  );
  session.revealCell(601, 73);
  contestant = getContestant(session, 601);
  assert.deepEqual(
    { score: contestant.score, cumtime: contestant.cumtime, tiebreaker: contestant.tiebreaker },
    { score: 100, cumtime: 1200, tiebreaker: 300 },
  );
  assertFinalParity(session, vnojLsoPayload, { 601: 1, 602: 2 }, [601, 602]);
});

test("VNOJ penalty zero ignores stored cell penalty counts", () => {
  const session = new ResolverSession(vnojNoPenaltyPayload, { baseline: "beginning" });
  assertFinalParity(session, vnojNoPenaltyPayload, { 701: 1 }, [701]);
});

test("ranking keeps tie-aware displayed ranks while accepting an explicit physical fallback", () => {
  const ranked = rankContestants([
    { participationId: 1, isDisqualified: false, score: 10, cumtime: 20, tiebreaker: 5, tieKey: 9 },
    { participationId: 2, isDisqualified: false, score: 10, cumtime: 20, tiebreaker: 5, tieKey: 1 },
    { participationId: 3, isDisqualified: false, score: 9, cumtime: 1, tiebreaker: 1, tieKey: 0 },
    { participationId: 4, isDisqualified: true, score: 100, cumtime: 0, tiebreaker: 0, tieKey: 0 },
  ]);
  assert.deepEqual(
    ranked.map((entry) => entry.contestantId),
    [2, 1, 3, 4],
  );
  assert.deepEqual(
    ranked.map((entry) => entry.rank),
    [1, 1, 3, 4],
  );
});

test("history restores exact states, supports forward, invalidates redo, and resets deterministically", () => {
  const session = new ResolverSession(defaultPayload, { baseline: "beginning", seed: "history" });
  const state0 = session.getState();
  const transitionA = session.revealCell(11, 101);
  const transitionB = session.revealCell(11, 305);
  session.revealCell(22, 101);

  assert.equal(session.back(), true);
  assert.deepEqual(session.getState(), transitionB.after);
  assert.equal(session.back(), true);
  assert.deepEqual(session.getState(), transitionA.after);
  assert.equal(session.forward(), true);
  assert.deepEqual(session.getState(), transitionB.after);

  session.revealCell(22, 305);
  assert.equal(session.forward(), false);
  const history = session.getHistory();
  assert.equal(history.cursor, 3);
  assert.deepEqual(
    history.transitions.map((item) => item.target),
    [
      { contestantId: 11, problemId: 101 },
      { contestantId: 11, problemId: 305 },
      { contestantId: 22, problemId: 305 },
    ],
  );

  assert.deepEqual(session.reset(), state0);
  assert.deepEqual(session.replay(), state0);
  const secondSession = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    seed: "history",
  });
  assert.deepEqual(secondSession.getState(), state0);
});

test("source payload is immutable and resolver operations do not mutate caller data", () => {
  const callerPayload = structuredClone(defaultPayload);
  const before = structuredClone(callerPayload);
  const session = new ResolverSession(callerPayload, { baseline: "beginning" });
  assert.equal(Object.isFrozen(session.source), true);
  assert.equal(Object.isFrozen(session.source.contestants[0].problems["101"].final), true);
  session.revealCell(11, 101);
  assert.deepEqual(callerPayload, before);
  assert.deepEqual(session.source, before);
});

test("a fully resolved disqualified contestant matches the stored final override", () => {
  const payload = structuredClone(defaultPayload);
  payload.contestants[0].is_disqualified = true;
  payload.contestants[0].final = { score: -9999, cumtime: 0, tiebreaker: 0 };
  const session = new ResolverSession(payload, { baseline: "beginning", seed: "dq" });

  assertFinalParity(session, payload, { 11: 3, 22: 1, 33: 2 }, [22, 33, 11]);
});

test("unsupported formats and unavailable official freezes reject clearly", () => {
  const unsupported = structuredClone(defaultPayload);
  unsupported.contest.format = "atcoder";
  assert.throws(() => new ResolverSession(unsupported), UnsupportedResolverFormatError);
  assert.throws(
    () => new ResolverSession(defaultPayload, { baseline: "official-freeze" }),
    UnsupportedResolverBaselineError,
  );
});

test("score rounding uses Python-compatible half-even behavior for exact halves", () => {
  assert.equal(roundLikePython(2.5), 2);
  assert.equal(roundLikePython(3.5), 4);
  assert.equal(roundLikePython(-2.5), -2);
  assert.equal(roundLikePython(1.225, 2), 1.23);
  assert.equal(roundLikePython(2.675, 2), 2.67);
});

test("bottom-up sticky policy selects the current lowest unresolved contestant and stays sticky", () => {
  const standings = [
    { contestantId: 1, position: 1 },
    { contestantId: 2, position: 2 },
    { contestantId: 3, position: 3 },
  ];
  const cells = [
    { contestantId: 1, problemId: "A" },
    { contestantId: 2, problemId: "A" },
    { contestantId: 2, problemId: "B" },
  ];
  assert.deepEqual(selectBottomUpStickyTarget(standings, cells), {
    contestantId: 2,
    problemId: "A",
  });
  assert.deepEqual(selectBottomUpStickyTarget(standings, cells, 1), {
    contestantId: 1,
    problemId: "A",
  });
  assert.equal(selectBottomUpStickyTarget(standings, [], 1), null);

  const session = new ResolverSession(defaultPayload, { baseline: "beginning", seed: "policy" });
  const policy = new BottomUpStickyPolicy();
  const first = policy.select(session);
  session.revealCell(first.contestantId, first.problemId);
  const remainingForSticky = session
    .getResolvableCells()
    .filter((cell) => String(cell.contestantId) === String(first.contestantId));
  const second = policy.select(session);
  if (remainingForSticky.length) {
    assert.equal(String(second.contestantId), String(first.contestantId));
  }
});

test("derived Total AC uses revealed state while first solve remains authoritative", () => {
  const session = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    seed: "presentation",
  });
  let stats = deriveProblemStats(defaultPayload, session.getState());
  assert.deepEqual(
    stats.map((stat) => [stat.problemId, stat.totalSolved, stat.firstSolveContestantId]),
    [
      [101, 0, null],
      [305, 0, null],
    ],
  );

  session.revealCell(22, 101);
  stats = deriveProblemStats(defaultPayload, session.getState());
  assert.deepEqual(
    [stats[0].totalSolved, stats[0].firstSolveContestantId, stats[0].firstSolveTime],
    [1, null, null],
  );
  session.revealCell(11, 101);
  stats = deriveProblemStats(defaultPayload, session.getState());
  assert.deepEqual(
    [stats[0].totalSolved, stats[0].firstSolveContestantId, stats[0].firstSolveTime],
    [2, 11, 100],
  );
});

test("frozen ICPC presentation hides final solve time until reveal", () => {
  const session = new ResolverSession(icpcPayload, {
    baseline: "official-freeze",
    seed: "presentation-freeze",
  });
  const contestant = getContestant(session, 101);
  const pending = getCellPresentation("icpc", contestant.problems["88"], 3);
  assert.equal(pending.primary, "2 tries");
  assert.equal(pending.secondary, "");
  assert.equal(pending.accessibleLabel.includes("60"), false);

  session.revealCell(101, 88);
  const revealed = getCellPresentation("icpc", getContestant(session, 101).problems["88"], 3);
  assert.equal(revealed.primary, "60");
  assert.equal(revealed.secondary, "2 tries");
});

test("VNOJ cell presentation matches frozen pending and revealed penalty structure", () => {
  const session = new ResolverSession(vnojPayload, { baseline: "official-freeze" });
  let cell = getContestant(session, 501).problems["9"];
  let presentation = getCellPresentation("vnoj", cell, 3);
  assert.deepEqual(
    {
      primary: presentation.primary,
      secondary: presentation.secondary,
      pendingCount: presentation.pendingCount,
      penalty: presentation.penalty,
    },
    { primary: "50?", secondary: "?", pendingCount: 2, penalty: 0 },
  );

  session.revealCell(501, 9);
  cell = getContestant(session, 501).problems["9"];
  presentation = getCellPresentation("vnoj", cell, 3);
  assert.deepEqual(
    {
      primary: presentation.primary,
      secondary: presentation.secondary,
      pendingCount: presentation.pendingCount,
      penalty: presentation.penalty,
    },
    { primary: "100", secondary: "10:00", pendingCount: 0, penalty: 2 },
  );
});

test("Phase 3 presets are deterministic and Director never starts an automatic policy", () => {
  assert.deepEqual(
    {
      baseline: CEREMONY_PRESETS.icpc.baseline,
      policy: CEREMONY_PRESETS.icpc.policy,
      tieOrder: CEREMONY_PRESETS.icpc.tieOrder,
    },
    { baseline: "auto", policy: "row-sweep", tieOrder: "seeded" },
  );
  assert.equal(CEREMONY_PRESETS.full.baseline, "beginning");
  assert.equal(CEREMONY_PRESETS.director.policy, "manual");
  assert.deepEqual(
    SPEED_PRESETS.map((preset) => preset.speed),
    [0.5, 1, 2, 4],
  );
  assert.equal(normalizeAwardPlaces(20, 8), 8);
  assert.equal(normalizeAwardPlaces(0, 8), 0);
});

test("source tie order is explicit while seeded Replay restores the exact baseline", () => {
  const sourceSession = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    tieOrder: "source",
  });
  assert.deepEqual(
    sourceSession.getState().standings.map((standing) => standing.contestantId),
    defaultPayload.contestants.map((contestant) => contestant.participation_id),
  );

  const seeded = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    tieOrder: "seeded",
    seed: "phase-3-replay",
  });
  const baseline = seeded.getState();
  seeded.revealCell(11, 101);
  assert.deepEqual(seeded.replay(), baseline);
});

test("semantic transition effects use authoritative first solve metadata", () => {
  const session = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    seed: "phase-3-effects",
  });
  const first = session.revealCell(11, 101);
  const later = session.revealCell(22, 101);
  assert.equal(first.effects.firstSolveAppeared, true);
  assert.equal(first.effects.authoritativeFirstSolveAppeared, true);
  assert.equal(later.effects.firstSolveAppeared, false);
});

test("authoritative first solve identity is stable regardless of reveal order", () => {
  const laterFirst = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    seed: "fts-later-first",
  });
  const nonAuthoritative = laterFirst.revealCell(22, 101);
  const authoritative = laterFirst.revealCell(11, 101);
  assert.equal(nonAuthoritative.effects.authoritativeFirstSolveAppeared, false);
  assert.equal(authoritative.effects.authoritativeFirstSolveAppeared, true);

  const authoritativeFirst = new ResolverSession(defaultPayload, {
    baseline: "beginning",
    seed: "fts-authoritative-first",
  });
  assert.equal(
    authoritativeFirst.revealCell(11, 101).effects.authoritativeFirstSolveAppeared,
    true,
  );
  assert.equal(defaultPayload.problems[0].first_solve_participation_id, 11);
});

test("by-problem and by-contestant policies choose semantic IDs without table columns", () => {
  const standings = [{ contestantId: 1 }, { contestantId: 2 }, { contestantId: 3 }];
  const cells = [
    { contestantId: 1, problemId: "B" },
    { contestantId: 2, problemId: "A" },
    { contestantId: 3, problemId: "A" },
  ];
  assert.deepEqual(selectByProblemTarget(standings, cells, ["A", "B"]), {
    contestantId: 3,
    problemId: "A",
  });
  assert.deepEqual(selectByProblemTarget(standings, cells, ["A", "B"], "B"), {
    contestantId: 1,
    problemId: "B",
  });
  assert.deepEqual(selectByContestantTarget(standings, cells), {
    contestantId: 1,
    problemId: "B",
  });

  const session = new ResolverSession(defaultPayload, { baseline: "beginning" });
  assert.ok(
    new ByProblemPolicy(defaultPayload.problems.map((problem) => problem.id)).select(session),
  );
  assert.ok(new ByContestantPolicy().select(session));
});

test("rank display options accept Avatar, Logo, and Hidden and fail safely to Hidden", () => {
  assert.equal(normalizeRankDisplayOption(1), 1);
  assert.equal(normalizeRankDisplayOption(2), 2);
  assert.equal(normalizeRankDisplayOption(3), 3);
  assert.equal(normalizeRankDisplayOption(undefined), 3);
  assert.equal(normalizeRankDisplayOption(null), 3);
  assert.equal(normalizeRankDisplayOption(99), 3);
});

test("multiple visible organizations retain display order, labels, and links", () => {
  assert.deepEqual(
    getOrganizationPresentation([
      { name: "Alpha Organization", short_name: "AO", url: "/organization/alpha" },
      { name: "Beta Organization", short_name: "", url: "/organization/beta" },
      { name: "", short_name: "", url: "/organization/invalid" },
    ]),
    [
      { label: "AO", url: "/organization/alpha" },
      { label: "Beta Organization", url: "/organization/beta" },
    ],
  );
  assert.deepEqual(getOrganizationPresentation(null), []);
});
