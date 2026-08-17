import { cellState, clone, hiddenCell, numeric, roundLikePython } from "../utils.js";

export const ICPCAdapter = Object.freeze({
  name: "icpc",

  createFinalCell(problem, payloadCell) {
    return cellState(problem, payloadCell ? payloadCell.final : null);
  },

  createBeginningCell(problem, payloadCell) {
    return payloadCell ? hiddenCell() : cellState(problem, null);
  },

  createFrozenCell(problem, payloadCell) {
    if (!payloadCell || !payloadCell.frozen || !payloadCell.frozen.pending) {
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
    const penaltyMinutes = numeric(contestConfig.penalty, 20);
    let score = 0;
    let cumtime = 0;
    let tiebreaker = 0;

    Object.values(problemStates).forEach((cell) => {
      if (cell.points === 0) {
        return;
      }
      const minute = Math.floor(cell.time / 60);
      score += cell.points;
      cumtime += minute + (numeric(cell.tries) - 1) * penaltyMinutes;
      tiebreaker = Math.max(tiebreaker, minute);
    });

    return {
      score: roundLikePython(score, pointsPrecision),
      cumtime: Math.max(cumtime, 0),
      tiebreaker,
    };
  },
});
