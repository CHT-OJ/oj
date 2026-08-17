function numeric(value) {
  return Number(value ?? 0);
}

export function formatScore(value, precision = 3) {
  const number = numeric(value);
  if (Number.isInteger(number)) {
    return String(number);
  }
  return number.toFixed(precision).replace(/0+$/, "").replace(/\.$/, "");
}

export function formatDuration(seconds) {
  const total = Math.max(0, Math.trunc(numeric(seconds)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainingSeconds = total % 60;
  if (hours) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(
      2,
      "0",
    )}`;
  }
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function attemptLabel(count) {
  return `${count} ${count === 1 ? "try" : "tries"}`;
}

function baseCellPresentation(cell) {
  return {
    state: cell.state,
    primary: "—",
    secondary: "",
    accessibleLabel: "No submissions",
    resolvable: cell.attempted && !cell.revealed,
  };
}

function presentICPC(cell) {
  const view = baseCellPresentation(cell);
  if (cell.state === "empty") {
    return view;
  }
  if (cell.state === "hidden") {
    return {
      ...view,
      primary: "?",
      secondary: "Unrevealed",
      accessibleLabel: "Unrevealed result",
    };
  }
  if (cell.state === "pending") {
    const tries = numeric(cell.tries);
    return {
      ...view,
      primary: tries ? attemptLabel(tries) : "?",
      secondary: "Pending",
      accessibleLabel: tries ? `${attemptLabel(tries)}, pending` : "Pending result",
    };
  }
  if (cell.state === "failed") {
    const tries = numeric(cell.tries);
    return {
      ...view,
      primary: attemptLabel(tries),
      accessibleLabel: `${attemptLabel(tries)}, not solved`,
    };
  }

  const minute = Math.floor(numeric(cell.time) / 60);
  const tries = numeric(cell.tries);
  return {
    ...view,
    primary: String(minute),
    secondary: attemptLabel(tries),
    accessibleLabel: `Solved at ${minute} minutes in ${attemptLabel(tries)}`,
  };
}

function presentDefault(cell, precision) {
  const view = baseCellPresentation(cell);
  if (cell.state === "empty") {
    return view;
  }
  if (cell.state === "hidden") {
    return {
      ...view,
      primary: "?",
      secondary: "Unrevealed",
      accessibleLabel: "Unrevealed result",
    };
  }
  const score = formatScore(cell.points, precision);
  const time = formatDuration(cell.time);
  return {
    ...view,
    primary: score,
    secondary: time,
    accessibleLabel: `${score} points at ${time}`,
  };
}

function presentVNOJ(cell, precision) {
  const view = baseCellPresentation(cell);
  if (cell.state === "empty") {
    return view;
  }
  if (cell.state === "hidden") {
    return {
      ...view,
      primary: "?",
      secondary: "Unrevealed",
      accessibleLabel: "Unrevealed result",
    };
  }
  if (cell.state === "pending") {
    const known = numeric(cell.points) !== 0 || numeric(cell.penalty) !== 0;
    const pending = numeric(cell.pending);
    const primary = `${known ? `${formatScore(cell.points, precision)}?` : "?"}${
      pending ? ` [${pending}]` : ""
    }`;
    return {
      ...view,
      primary,
      secondary: "Pending",
      accessibleLabel: `${primary}, pending result`,
    };
  }

  const score = formatScore(cell.points, precision);
  const penalty = numeric(cell.penalty);
  const primary = penalty ? `${score} (+${penalty})` : score;
  const time = formatDuration(cell.time);
  return {
    ...view,
    primary,
    secondary: time,
    accessibleLabel: `${score} points${penalty ? ` with ${penalty} penalties` : ""} at ${time}`,
  };
}

export function getCellPresentation(formatName, cell, precision = 3) {
  if (formatName === "icpc") {
    return presentICPC(cell);
  }
  if (formatName === "vnoj") {
    return presentVNOJ(cell, precision);
  }
  if (formatName === "default") {
    return presentDefault(cell, precision);
  }
  throw new RangeError(`Unsupported Resolver presentation format "${formatName}".`);
}

export function getMetricPresentation(formatName, contestant, precision = 3) {
  if (formatName === "icpc") {
    return {
      scoreLabel: "Solved",
      score: formatScore(contestant.score, precision),
      timeLabel: "Penalty",
      time: String(Math.trunc(numeric(contestant.cumtime))),
    };
  }
  return {
    scoreLabel: "Score",
    score: formatScore(contestant.score, precision),
    timeLabel: "Time",
    time: formatDuration(contestant.cumtime),
  };
}

export function deriveProblemStats(payload, state) {
  const contestants = new Map(
    state.contestants.map((contestant) => [String(contestant.participationId), contestant]),
  );

  return [...payload.problems]
    .sort(
      (left, right) => left.order - right.order || String(left.id).localeCompare(String(right.id)),
    )
    .map((problem) => {
      let totalSolved = 0;
      let firstSolveContestantId = null;
      let firstSolveTime = null;

      state.contestants.forEach((contestant) => {
        const cell = contestants.get(String(contestant.participationId)).problems[
          String(problem.id)
        ];
        if (!cell || cell.state !== "solved") {
          return;
        }
        totalSolved += 1;
        if (firstSolveTime === null || numeric(cell.time) < firstSolveTime) {
          firstSolveTime = numeric(cell.time);
          firstSolveContestantId = contestant.participationId;
        }
      });

      return {
        problemId: problem.id,
        totalSolved,
        firstSolveContestantId,
        firstSolveTime,
      };
    });
}
