import { cellState, clone, hiddenCell, roundLikePython } from "../utils.js";

export const DefaultAdapter = Object.freeze({
  name: "default",

  createFinalCell(problem, payloadCell) {
    return cellState(problem, payloadCell ? payloadCell.final : null);
  },

  createBeginningCell(problem, payloadCell) {
    return payloadCell ? hiddenCell() : cellState(problem, null);
  },

  createFrozenCell() {
    throw new Error("The default contest format has no official-freeze baseline.");
  },

  isResolvable(currentCell) {
    return currentCell.attempted && !currentCell.revealed;
  },

  revealCell(currentCell, finalCell) {
    return this.isResolvable(currentCell) ? clone(finalCell) : clone(currentCell);
  },

  recomputeContestant(contestant, problemStates, contestConfig, pointsPrecision) {
    let score = 0;
    let cumtime = 0;
    Object.values(problemStates).forEach((cell) => {
      score += cell.points;
      if (cell.points !== 0) {
        cumtime += cell.time;
      }
    });
    return {
      score: roundLikePython(score, pointsPrecision),
      cumtime: Math.trunc(Math.max(cumtime, 0)),
      tiebreaker: 0,
    };
  },
});
