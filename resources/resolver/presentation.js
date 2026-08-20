import { gettext, ngettext } from "./i18n.js";

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

export function normalizeRankDisplayOption(value) {
  const option = Number(value);
  return option === 1 || option === 2 || option === 3 ? option : 3;
}

export function getOrganizationPresentation(organizations) {
  if (!Array.isArray(organizations)) {
    return [];
  }
  return organizations
    .map((organization) => {
      const label = organization?.short_name || organization?.name;
      if (!label) {
        return null;
      }
      return {
        label: String(label),
        url: organization.url ? String(organization.url) : null,
      };
    })
    .filter(Boolean);
}

function attemptLabel(count) {
  return ngettext("%(count)s try", "%(count)s tries", count, { count });
}

function baseCellPresentation(cell) {
  return {
    state: cell.state,
    primary: "",
    secondary: "",
    accessibleLabel: gettext("No submissions"),
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
      secondary: gettext("Unrevealed"),
      accessibleLabel: gettext("Unrevealed result"),
    };
  }
  if (cell.state === "pending") {
    const tries = numeric(cell.tries);
    return {
      ...view,
      primary: tries ? attemptLabel(tries) : "?",
      secondary: "",
      accessibleLabel: tries
        ? gettext("%(tries)s, pending", { tries: attemptLabel(tries) })
        : gettext("Pending result"),
    };
  }
  if (cell.state === "failed") {
    const tries = numeric(cell.tries);
    if (!tries) {
      return {
        ...view,
        state: "empty",
        primary: "",
        accessibleLabel: gettext("No countable submissions"),
      };
    }
    return {
      ...view,
      primary: attemptLabel(tries),
      accessibleLabel: gettext("%(tries)s, not solved", { tries: attemptLabel(tries) }),
    };
  }

  const minute = Math.floor(numeric(cell.time) / 60);
  const tries = numeric(cell.tries);
  return {
    ...view,
    primary: String(minute),
    secondary: attemptLabel(tries),
    minute,
    tries,
    time: formatDuration(cell.time),
    accessibleLabel: gettext("Solved at %(minute)s minutes in %(tries)s", {
      minute,
      tries: attemptLabel(tries),
    }),
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
      secondary: gettext("Unrevealed"),
      accessibleLabel: gettext("Unrevealed result"),
    };
  }
  const score = formatScore(cell.points, precision);
  const time = formatDuration(cell.time);
  return {
    ...view,
    primary: score,
    secondary: time,
    time,
    accessibleLabel: gettext("%(score)s points at %(time)s", { score, time }),
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
      secondary: gettext("Unrevealed"),
      accessibleLabel: gettext("Unrevealed result"),
    };
  }
  if (cell.state === "pending") {
    const known = numeric(cell.points) !== 0 || numeric(cell.penalty) !== 0;
    const pending = numeric(cell.pending);
    const primary = known ? `${formatScore(cell.points, precision)}?` : "?";
    return {
      ...view,
      primary,
      secondary: "?",
      pendingCount: pending,
      penalty: 0,
      accessibleLabel: gettext("%(result)s, pending result", {
        result: `${primary}${pending ? ` [${pending}]` : ""}`,
      }),
    };
  }

  const score = formatScore(cell.points, precision);
  const penalty = numeric(cell.penalty);
  const time = formatDuration(cell.time);
  return {
    ...view,
    primary: score,
    secondary: time,
    penalty,
    pendingCount: 0,
    time,
    accessibleLabel: penalty
      ? gettext("%(score)s points with %(penalty)s penalties at %(time)s", {
          score,
          penalty,
          time,
        })
      : gettext("%(score)s points at %(time)s", { score, time }),
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
  throw new RangeError(
    gettext('Unsupported Resolver presentation format "%(format)s".', { format: formatName }),
  );
}

export function getMetricPresentation(formatName, contestant, precision = 3) {
  if (formatName === "icpc") {
    return {
      scoreLabel: gettext("Solved"),
      score: formatScore(contestant.score, precision),
      timeLabel: gettext("Penalty"),
      time: String(Math.trunc(numeric(contestant.cumtime))),
    };
  }
  return {
    scoreLabel: gettext("Score"),
    score: formatScore(contestant.score, precision),
    timeLabel: gettext("Time"),
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
      const authoritativeFirstSolveContestantId = problem.first_solve_participation_id ?? null;
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
        if (
          authoritativeFirstSolveContestantId !== null &&
          String(authoritativeFirstSolveContestantId) === String(contestant.participationId)
        ) {
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
