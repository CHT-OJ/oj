function normalizeId(value) {
  return String(value);
}

function lastRevealedTarget(session) {
  return session.getLastTransition()?.target ?? null;
}

function orderedContestantCells(cells, problemOrder) {
  const order = new Map(problemOrder.map((problemId, index) => [normalizeId(problemId), index]));
  return [...cells].sort(
    (left, right) =>
      (order.get(normalizeId(left.problemId)) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(normalizeId(right.problemId)) ?? Number.MAX_SAFE_INTEGER) ||
      normalizeId(left.problemId).localeCompare(normalizeId(right.problemId)),
  );
}

function predeterminedProblemFor(predeterminedProblems, contestantId) {
  if (predeterminedProblems instanceof Map) {
    return (
      predeterminedProblems.get(contestantId) ??
      predeterminedProblems.get(normalizeId(contestantId))
    );
  }
  return (
    predeterminedProblems?.[contestantId] ?? predeterminedProblems?.[normalizeId(contestantId)]
  );
}

export function selectRowSweepTarget(
  standings,
  resolvableCells,
  problemOrder,
  predeterminedProblems = {},
) {
  const cellsByContestant = new Map();
  resolvableCells.forEach((cell) => {
    const contestantId = normalizeId(cell.contestantId);
    if (!cellsByContestant.has(contestantId)) {
      cellsByContestant.set(contestantId, []);
    }
    cellsByContestant.get(contestantId).push(cell);
  });

  for (let index = standings.length - 1; index >= 0; index -= 1) {
    const standing = standings[index];
    const cells = orderedContestantCells(
      cellsByContestant.get(normalizeId(standing.contestantId)) ?? [],
      problemOrder,
    );
    if (!cells.length) {
      continue;
    }
    const predeterminedProblem = predeterminedProblemFor(
      predeterminedProblems,
      standing.contestantId,
    );
    const predetermined = cells.find(
      (cell) => normalizeId(cell.problemId) === normalizeId(predeterminedProblem),
    );
    return predetermined ?? cells[0];
  }
  return null;
}

export class RowSweepPolicy {
  constructor(problemOrder, predeterminedProblems = {}) {
    this.problemOrder = [...problemOrder];
    this.predeterminedProblems = predeterminedProblems;
  }

  select(session) {
    return selectRowSweepTarget(
      session.getStandings(),
      session.getResolvableCells(),
      this.problemOrder,
      this.predeterminedProblems,
    );
  }

  clear() {}
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
  select(session) {
    const previous = lastRevealedTarget(session);
    const target = selectBottomUpStickyTarget(
      session.getStandings(),
      session.getResolvableCells(),
      previous?.contestantId ?? null,
    );
    return target;
  }

  clear() {}
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
  }

  select(session) {
    const previous = lastRevealedTarget(session);
    const target = selectByProblemTarget(
      session.getStandings(),
      session.getResolvableCells(),
      this.problemOrder,
      previous?.problemId ?? null,
    );
    return target;
  }

  clear() {}
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
  select(session) {
    const previous = lastRevealedTarget(session);
    const target = selectByContestantTarget(
      session.getStandings(),
      session.getResolvableCells(),
      previous?.contestantId ?? null,
    );
    return target;
  }

  clear() {}
}
