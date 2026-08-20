export function createSyntheticPayload(contestantCount, problemCount) {
  const problems = Array.from({ length: problemCount }, (_, index) => ({
    id: 1000 + index,
    code: `problem-${index + 1}`,
    label: String.fromCharCode(65 + (index % 26)),
    name: `Synthetic problem ${index + 1}`,
    order: index,
    max_score: 100,
    first_solve_participation_id: index === 0 ? 1 : null,
    final_total_ac: contestantCount,
  }));

  const contestants = Array.from({ length: contestantCount }, (_, contestantIndex) => {
    const participationId = contestantIndex + 1;
    const problemCells = {};
    let score = 0;
    let cumtime = 0;
    problems.forEach((problem, problemIndex) => {
      const points = 100 - ((contestantIndex + problemIndex) % 5) * 10;
      const time = 60 * (problemIndex + 1) + contestantIndex;
      score += points;
      cumtime += time;
      problemCells[problem.id] = {
        problem_id: problem.id,
        attempted: true,
        final: { points, time },
        frozen: null,
      };
    });
    return {
      participation_id: participationId,
      profile_id: 10000 + participationId,
      username: `synthetic-${participationId}`,
      display_name: `Synthetic ${participationId}`,
      full_name: "",
      user_css_class: "rating rate-none user",
      profile_url: `/user/synthetic-${participationId}`,
      avatar_url: null,
      rank_logo_url: null,
      organizations: [],
      is_disqualified: false,
      submission_count: problemCount,
      final: { score, cumtime, tiebreaker: 0 },
      frozen: null,
      problems: problemCells,
      final_order: contestantIndex,
      frozen_order: contestantIndex,
    };
  });

  return {
    schema_version: 1,
    contest: {
      id: 999,
      key: `synthetic-${contestantCount}x${problemCount}`,
      name: "Synthetic Resolver benchmark",
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
