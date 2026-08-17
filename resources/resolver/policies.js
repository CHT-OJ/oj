function normalizeId(value) {
  return String(value);
}

export function selectBottomUpStickyTarget(standings, resolvableCells, stickyContestantId = null) {
  const cellsByContestant = new Map();
  resolvableCells.forEach((cell) => {
    const contestantId = normalizeId(cell.contestantId);
    if (!cellsByContestant.has(contestantId)) {
      cellsByContestant.set(contestantId, []);
    }
    cellsByContestant.get(contestantId).push(cell);
  });

  if (stickyContestantId !== null) {
    const stickyCells = cellsByContestant.get(normalizeId(stickyContestantId));
    if (stickyCells && stickyCells.length) {
      return stickyCells[0];
    }
  }

  for (let index = standings.length - 1; index >= 0; index -= 1) {
    const cells = cellsByContestant.get(normalizeId(standings[index].contestantId));
    if (cells && cells.length) {
      return cells[0];
    }
  }
  return null;
}

export class BottomUpStickyPolicy {
  constructor() {
    this.stickyContestantId = null;
  }

  select(session) {
    const target = selectBottomUpStickyTarget(
      session.getState().standings,
      session.getResolvableCells(),
      this.stickyContestantId,
    );
    this.stickyContestantId = target ? target.contestantId : null;
    return target;
  }

  clear() {
    this.stickyContestantId = null;
  }
}

function selectCellForProblem(standings, resolvableCells, problemId) {
  const contestants = new Set(
    resolvableCells
      .filter((cell) => normalizeId(cell.problemId) === normalizeId(problemId))
      .map((cell) => normalizeId(cell.contestantId)),
  );
  for (let index = standings.length - 1; index >= 0; index -= 1) {
    if (contestants.has(normalizeId(standings[index].contestantId))) {
      return resolvableCells.find(
        (cell) =>
          normalizeId(cell.problemId) === normalizeId(problemId) &&
          normalizeId(cell.contestantId) === normalizeId(standings[index].contestantId),
      );
    }
  }
  return null;
}

export function selectByProblemTarget(
  standings,
  resolvableCells,
  problemOrder,
  stickyProblemId = null,
) {
  if (stickyProblemId !== null) {
    const stickyTarget = selectCellForProblem(standings, resolvableCells, stickyProblemId);
    if (stickyTarget) {
      return stickyTarget;
    }
  }
  for (const problemId of problemOrder) {
    const target = selectCellForProblem(standings, resolvableCells, problemId);
    if (target) {
      return target;
    }
  }
  return null;
}

export class ByProblemPolicy {
  constructor(problemOrder) {
    this.problemOrder = [...problemOrder];
    this.stickyProblemId = null;
  }

  select(session) {
    const target = selectByProblemTarget(
      session.getState().standings,
      session.getResolvableCells(),
      this.problemOrder,
      this.stickyProblemId,
    );
    this.stickyProblemId = target ? target.problemId : null;
    return target;
  }

  clear() {
    this.stickyProblemId = null;
  }
}

export function selectByContestantTarget(standings, resolvableCells, stickyContestantId = null) {
  const cellsByContestant = new Map();
  resolvableCells.forEach((cell) => {
    const contestantId = normalizeId(cell.contestantId);
    if (!cellsByContestant.has(contestantId)) {
      cellsByContestant.set(contestantId, []);
    }
    cellsByContestant.get(contestantId).push(cell);
  });
  if (stickyContestantId !== null) {
    const stickyCells = cellsByContestant.get(normalizeId(stickyContestantId));
    if (stickyCells?.length) {
      return stickyCells[0];
    }
  }
  for (const standing of standings) {
    const cells = cellsByContestant.get(normalizeId(standing.contestantId));
    if (cells?.length) {
      return cells[0];
    }
  }
  return null;
}

export class ByContestantPolicy {
  constructor() {
    this.stickyContestantId = null;
  }

  select(session) {
    const target = selectByContestantTarget(
      session.getState().standings,
      session.getResolvableCells(),
      this.stickyContestantId,
    );
    this.stickyContestantId = target ? target.contestantId : null;
    return target;
  }

  clear() {
    this.stickyContestantId = null;
  }
}
