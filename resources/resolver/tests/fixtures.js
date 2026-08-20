function problem(id, code, label, order, maxScore = 100, firstSolve = null, totalAc = 0) {
  return {
    id,
    code,
    label,
    name: `Problem ${label}`,
    order,
    max_score: maxScore,
    first_solve_participation_id: firstSolve,
    final_total_ac: totalAc,
  };
}

function contestant(id, name, final, problems, frozen = null, submissionCount = 0) {
  return {
    participation_id: id,
    profile_id: id + 1000,
    username: name,
    display_name: name.toUpperCase(),
    full_name: `${name} full name`,
    user_css_class: "rating rate-none user",
    profile_url: `/user/${name}`,
    avatar_url: null,
    rank_logo_url: null,
    organizations: [],
    is_disqualified: false,
    submission_count: submissionCount,
    final,
    frozen,
    problems,
  };
}

function payload(
  format,
  formatConfig,
  problems,
  contestants,
  frozen = false,
  finalOrder = null,
  frozenOrder = null,
) {
  const finalOrderMap = new Map(
    (finalOrder ?? contestants.map((entry) => entry.participation_id)).map((id, index) => [
      id,
      index,
    ]),
  );
  const frozenOrderMap = new Map(
    (frozenOrder ?? finalOrder ?? contestants.map((entry) => entry.participation_id)).map(
      (id, index) => [id, index],
    ),
  );
  return {
    schema_version: 1,
    contest: {
      id: 1,
      key: `resolver-${format}`,
      name: `${format} Resolver Fixture`,
      format,
      format_config: formatConfig,
      rank_display_options: 3,
      points_precision: 3,
      frozen_last_minutes: frozen ? 60 : 0,
      official_freeze_available: frozen,
    },
    problems,
    contestants: contestants.map((entry) => ({
      ...entry,
      final_order: finalOrderMap.get(entry.participation_id),
      frozen_order: frozenOrderMap.get(entry.participation_id),
    })),
  };
}

function defaultCell(problemId, points, time) {
  return {
    problem_id: problemId,
    attempted: true,
    final: { points, time },
    frozen: null,
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

function vnojCell(
  problemId,
  points,
  time,
  penalty,
  pending,
  frozenPoints,
  frozenTime,
  frozenPenalty,
) {
  return {
    problem_id: problemId,
    attempted: true,
    final: { points, time, penalty, pending },
    frozen: {
      points: frozenPoints,
      time: frozenTime,
      penalty: frozenPenalty,
      pending,
    },
  };
}

const defaultProblems = [problem(101, "alpha", "1", 7, 100, 11, 2), problem(305, "beta", "2", 20)];

export const defaultPayload = payload(
  "default",
  {},
  defaultProblems,
  [
    contestant(
      11,
      "alpha",
      { score: 150, cumtime: 300, tiebreaker: 0 },
      {
        101: defaultCell(101, 100, 100),
        305: defaultCell(305, 50, 200),
      },
      null,
      10,
    ),
    contestant(
      22,
      "bravo",
      { score: 150, cumtime: 300, tiebreaker: 0 },
      {
        101: defaultCell(101, 100, 180),
        305: defaultCell(305, 50, 120),
      },
      null,
      99,
    ),
    contestant(
      33,
      "charlie",
      { score: 0, cumtime: 0, tiebreaker: 0 },
      {
        101: defaultCell(101, 0, 50),
      },
    ),
  ],
  false,
  [22, 11, 33],
);

const icpcProblems = [
  problem(17, "a", "A", 2, 1, 101, 3),
  problem(42, "b", "B", 9, 1, 303, 2),
  problem(88, "c", "C", 15, 1, 101, 1),
];

export const icpcPayload = payload(
  "icpc",
  { penalty: 15 },
  icpcProblems,
  [
    contestant(
      101,
      "pending-team",
      { score: 2, cumtime: 85, tiebreaker: 60 },
      {
        17: icpcCell(17, 1, 600, 1, 1, 1, false),
        42: icpcCell(42, 0, 2400, 3, 0, 2, true),
        88: icpcCell(88, 1, 3600, 2, 0, 2, true),
      },
      { score: 1, cumtime: 10, tiebreaker: 10 },
      12,
    ),
    contestant(
      202,
      "steady-team",
      { score: 2, cumtime: 85, tiebreaker: 50 },
      {
        17: icpcCell(17, 1, 1200, 2, 1, 2, false),
        42: icpcCell(42, 1, 3000, 1, 1, 1, false),
      },
      { score: 2, cumtime: 85, tiebreaker: 50 },
      2,
    ),
    contestant(
      303,
      "tied-team",
      { score: 2, cumtime: 85, tiebreaker: 50 },
      {
        17: icpcCell(17, 1, 1200, 1, 1, 1, false),
        42: icpcCell(42, 1, 3000, 2, 1, 2, false),
      },
      { score: 2, cumtime: 85, tiebreaker: 50 },
      200,
    ),
  ],
  true,
  [303, 202, 101],
  [303, 202, 101],
);

const vnojProblems = [problem(9, "x", "1", 4, 100, 503, 2), problem(73, "y", "2", 12)];

export const vnojPayload = payload(
  "vnoj",
  { penalty: 5, LSO: false },
  vnojProblems,
  [
    contestant(
      501,
      "improving",
      { score: 100, cumtime: 1200, tiebreaker: 600 },
      {
        9: vnojCell(9, 100, 600, 2, 2, 50, 300, 1),
        73: vnojCell(73, 0, 400, 3, 0, 0, 400, 3),
      },
      { score: 50, cumtime: 600, tiebreaker: 300 },
    ),
    contestant(
      502,
      "partials",
      { score: 100, cumtime: 1300, tiebreaker: 900 },
      {
        9: vnojCell(9, 50, 900, 0, 0, 50, 900, 0),
        73: vnojCell(73, 50, 100, 1, 0, 50, 100, 1),
      },
      { score: 100, cumtime: 1300, tiebreaker: 900 },
    ),
    contestant(
      503,
      "already-full",
      { score: 100, cumtime: 200, tiebreaker: 200 },
      {
        9: vnojCell(9, 100, 200, 0, 1, 100, 200, 0),
      },
      { score: 100, cumtime: 200, tiebreaker: 200 },
    ),
  ],
  true,
  [503, 501, 502],
  [503, 502, 501],
);

const vnojLsoProblems = [problem(9, "x", "1", 4, 100, 602, 1), problem(73, "y", "2", 12)];

export const vnojLsoPayload = payload(
  "vnoj",
  { penalty: 5, LSO: true },
  vnojLsoProblems,
  [
    contestant(
      601,
      "lso-team",
      { score: 100, cumtime: 1200, tiebreaker: 300 },
      {
        9: vnojCell(9, 50, 100, 1, 0, 0, 0, 0),
        73: vnojCell(73, 50, 300, 2, 0, 0, 0, 0),
      },
    ),
    contestant(
      602,
      "later-team",
      { score: 100, cumtime: 1250, tiebreaker: 1250 },
      {
        9: vnojCell(9, 100, 1250, 0, 0, 0, 0, 0),
      },
    ),
  ],
  false,
  [601, 602],
);

const vnojNoPenaltyProblems = [problem(9, "x", "1", 4, 100, 701, 1), problem(73, "y", "2", 12)];

export const vnojNoPenaltyPayload = payload(
  "vnoj",
  { penalty: 0, LSO: false },
  vnojNoPenaltyProblems,
  [
    contestant(
      701,
      "no-penalty",
      { score: 100, cumtime: 600, tiebreaker: 600 },
      {
        9: vnojCell(9, 100, 600, 7, 0, 0, 0, 0),
      },
    ),
  ],
);
