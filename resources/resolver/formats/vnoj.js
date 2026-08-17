import { cellState, clone, hiddenCell, numeric, roundLikePython } from "../utils.js";

export const VNOJAdapter = Object.freeze({
  name: "vnoj",

  createFinalCell(problem, payloadCell) {
    return cellState(problem, payloadCell ? payloadCell.final : null, { pending: 0 });
  },

  createBeginningCell(problem, payloadCell) {
    return payloadCell ? hiddenCell() : cellState(problem, null);
  },

  createFrozenCell(problem, payloadCell) {
    if (
      !payloadCell ||
      !payloadCell.frozen ||
      !payloadCell.frozen.pending ||
      numeric(payloadCell.frozen.points) === numeric(problem.max_score)
    ) {
      return this.createFinalCell(problem, payloadCell);
    }
    return cellState(problem, payloadCell.frozen, {
      state: "pending",
      revealed: false,
    });
  },

  isResolvable(currentCell) {
    return currentCell.attempted && !currentCell.revealed;
  },

  revealCell(currentCell, finalCell) {
    return this.isResolvable(currentCell) ? clone(finalCell) : clone(currentCell);
  },

  recomputeContestant(contestant, problemStates, contestConfig, pointsPrecision) {
    const penaltyMinutes = numeric(contestConfig.penalty, 5);
    const lastSubmissionOnly = contestConfig.LSO === true;
    let score = 0;
    let summedTime = 0;
    let penaltySeconds = 0;
    let tiebreaker = 0;

    Object.values(problemStates).forEach((cell) => {
      score += cell.points;
      if (cell.points === 0) {
        return;
      }
      summedTime += cell.time;
      tiebreaker = Math.max(tiebreaker, cell.time);
      penaltySeconds += numeric(cell.penalty) * penaltyMinutes * 60;
    });

    const scoringTime = lastSubmissionOnly ? tiebreaker : summedTime;
    return {
      score: roundLikePython(score, pointsPrecision),
      cumtime: Math.trunc(Math.max(scoringTime + penaltySeconds, 0)),
      tiebreaker,
    };
  },
});
