import { DefaultAdapter } from "./formats/default.js";
import { ICPCAdapter } from "./formats/icpc.js";
import { VNOJAdapter } from "./formats/vnoj.js";
import { gettext } from "./i18n.js";
import {
  createDeterministicTieKeys,
  createSourceOrderTieKeys,
  rankContestants,
} from "./ranking.js";
import { clone, deepFreeze } from "./utils.js";

const ADAPTERS = Object.freeze({
  default: DefaultAdapter,
  icpc: ICPCAdapter,
  vnoj: VNOJAdapter,
});
const EMPTY_TARGETS = Object.freeze([]);

export class UnsupportedResolverFormatError extends Error {
  constructor(formatName) {
    super(
      gettext('Contest format "%(format)s" is not supported by Resolver.', {
        format: formatName,
      }),
    );
    this.name = "UnsupportedResolverFormatError";
    this.formatName = formatName;
  }
}

export class UnsupportedResolverBaselineError extends Error {
  constructor(baseline) {
    super(
      gettext('Resolver baseline "%(baseline)s" is not available for this contest.', {
        baseline,
      }),
    );
    this.name = "UnsupportedResolverBaselineError";
    this.baseline = baseline;
  }
}

function validatePayload(payload) {
  if (
    !payload ||
    payload.schema_version !== 1 ||
    !payload.contest ||
    !Array.isArray(payload.problems) ||
    !Array.isArray(payload.contestants)
  ) {
    throw new TypeError(gettext("Invalid Resolver schema version 1 payload."));
  }
}

function normalizeBaseline(payload, requested) {
  const baseline =
    requested === "auto"
      ? payload.contest.official_freeze_available
        ? "official-freeze"
        : "beginning"
      : requested;
  if (baseline !== "beginning" && baseline !== "official-freeze") {
    throw new UnsupportedResolverBaselineError(baseline);
  }
  if (baseline === "official-freeze" && !payload.contest.official_freeze_available) {
    throw new UnsupportedResolverBaselineError(baseline);
  }
  return baseline;
}

function normalizeContestant(sourceContestant, tieKey) {
  const organizations = Array.isArray(sourceContestant.organizations)
    ? sourceContestant.organizations
    : sourceContestant.organization
    ? [sourceContestant.organization]
    : [];
  return {
    participationId: sourceContestant.participation_id,
    profileId: sourceContestant.profile_id,
    username: sourceContestant.username,
    displayName: sourceContestant.display_name,
    fullName: sourceContestant.full_name ?? "",
    cssClass: sourceContestant.user_css_class,
    profileUrl: sourceContestant.profile_url,
    avatarUrl: sourceContestant.avatar_url,
    rankLogoUrl: sourceContestant.rank_logo_url,
    organizations: clone(organizations),
    isDisqualified: sourceContestant.is_disqualified === true,
    submissionCount: sourceContestant.submission_count,
    finalOrder: Number.isFinite(sourceContestant.final_order)
      ? sourceContestant.final_order
      : tieKey,
    frozenOrder: Number.isFinite(sourceContestant.frozen_order)
      ? sourceContestant.frozen_order
      : tieKey,
    tieKey,
    score: 0,
    cumtime: 0,
    tiebreaker: 0,
    problems: {},
  };
}

export class ResolverSession {
  constructor(payload, options = {}) {
    validatePayload(payload);
    this.source = deepFreeze(clone(payload));

    const formatName = this.source.contest.format;
    this.adapter = ADAPTERS[formatName];
    if (!this.adapter) {
      throw new UnsupportedResolverFormatError(formatName);
    }

    this.baseline = normalizeBaseline(this.source, options.baseline ?? "auto");
    this.tieOrder = options.tieOrder ?? "seeded";
    if (this.tieOrder !== "seeded" && this.tieOrder !== "source") {
      throw new TypeError(
        gettext('Unknown Resolver tie order "%(order)s".', { order: this.tieOrder }),
      );
    }
    const defaultSeed = `${this.source.contest.key}:${this.source.contestants
      .map((contestant) => contestant.participation_id)
      .sort()
      .join(",")}`;
    this.seed = String(options.seed ?? defaultSeed);
    this._sourceContestants = new Map(
      this.source.contestants.map((contestant) => [
        String(contestant.participation_id),
        contestant,
      ]),
    );
    this._orderedProblems = Object.freeze(
      [...this.source.problems].sort(
        (left, right) =>
          left.order - right.order || String(left.id).localeCompare(String(right.id)),
      ),
    );
    this._problems = new Map(this._orderedProblems.map((problem) => [String(problem.id), problem]));
    this._finalCells = this._buildFinalCells();
    this._transitionSerial = 0;
    this._history = [];
    this._historyCursor = 0;
    this._revision = 0;
    this._resolvableCache = null;

    const initial = this._createInitialState();
    this._baselineState = deepFreeze(clone(initial));
    this._state = clone(initial);
  }

  _buildFinalCells() {
    const finalCells = {};
    this.source.contestants.forEach((contestant) => {
      const contestantId = String(contestant.participation_id);
      finalCells[contestantId] = {};
      this._orderedProblems.forEach((problem) => {
        const problemId = String(problem.id);
        const payloadCell = contestant.problems[problemId] ?? null;
        finalCells[contestantId][problemId] = deepFreeze(
          this.adapter.createFinalCell(problem, payloadCell),
        );
      });
    });
    return deepFreeze(finalCells);
  }

  _createInitialState() {
    let tieKeys;
    if (this.tieOrder === "source") {
      tieKeys = createSourceOrderTieKeys(this.source.contestants);
    } else if (
      this.baseline === "official-freeze" &&
      this.source.contestants.every((contestant) => Number.isFinite(contestant.frozen_order))
    ) {
      tieKeys = new Map(
        this.source.contestants.map((contestant) => [
          String(contestant.participation_id),
          contestant.frozen_order,
        ]),
      );
    } else {
      tieKeys = createDeterministicTieKeys(this.source.contestants, this.seed);
    }
    const contestants = this.source.contestants.map((sourceContestant) => {
      const contestantId = String(sourceContestant.participation_id);
      const contestant = normalizeContestant(sourceContestant, tieKeys.get(contestantId));

      this._orderedProblems.forEach((problem) => {
        const problemId = String(problem.id);
        const payloadCell = sourceContestant.problems[problemId] ?? null;
        contestant.problems[problemId] =
          this.baseline === "beginning"
            ? this.adapter.createBeginningCell(problem, payloadCell)
            : this.adapter.createFrozenCell(problem, payloadCell);
      });
      this._recomputeContestant(contestant);
      return contestant;
    });

    const state = { contestants, standings: [] };
    this._rerankState(state);
    return state;
  }

  _findContestantInState(state, contestantId) {
    const normalized = String(contestantId);
    return state.contestants.find(
      (contestant) => String(contestant.participationId) === normalized,
    );
  }

  _findContestant(contestantId) {
    return this._findContestantInState(this._state, contestantId);
  }

  _isFullyResolved(contestant) {
    return Object.values(contestant.problems).every((cell) => !this.adapter.isResolvable(cell));
  }

  _recomputeContestant(contestant) {
    const metrics = this.adapter.recomputeContestant(
      contestant,
      contestant.problems,
      this.source.contest.format_config,
      this.source.contest.points_precision,
    );

    if (contestant.isDisqualified && this._isFullyResolved(contestant)) {
      const sourceContestant = this._sourceContestants.get(String(contestant.participationId));
      Object.assign(metrics, sourceContestant.final);
    }
    contestant.score = metrics.score;
    contestant.cumtime = metrics.cumtime;
    contestant.tiebreaker = metrics.tiebreaker;
  }

  _isStateFullyResolved(state) {
    return state.contestants.every((contestant) => this._isFullyResolved(contestant));
  }

  _rerankState(state) {
    state.standings = rankContestants(state.contestants, {
      fallback: this._isStateFullyResolved(state) ? "finalOrder" : "tieKey",
    });
  }

  _rerank() {
    this._rerankState(this._state);
  }

  _advanceRevision() {
    this._revision += 1;
    this._resolvableCache = null;
  }

  _buildResolvableCache() {
    if (this._resolvableCache?.revision === this._revision) {
      return this._resolvableCache;
    }
    const cells = [];
    const byContestant = new Map();
    const byProblem = new Map();
    this._state.contestants.forEach((contestant) => {
      this._orderedProblems.forEach((problem) => {
        const problemId = String(problem.id);
        if (!this.adapter.isResolvable(contestant.problems[problemId])) {
          return;
        }
        const target = Object.freeze({
          contestantId: contestant.participationId,
          problemId: problem.id,
        });
        cells.push(target);
        const contestantKey = String(contestant.participationId);
        if (!byContestant.has(contestantKey)) {
          byContestant.set(contestantKey, []);
        }
        byContestant.get(contestantKey).push(target);
        if (!byProblem.has(problemId)) {
          byProblem.set(problemId, []);
        }
        byProblem.get(problemId).push(target);
      });
    });
    byContestant.forEach((targets) => Object.freeze(targets));
    byProblem.forEach((targets) => Object.freeze(targets));
    this._resolvableCache = {
      revision: this._revision,
      cells: Object.freeze(cells),
      byContestant,
      byProblem,
    };
    return this._resolvableCache;
  }

  getState() {
    return clone(this._state);
  }

  getStandings() {
    return this._state.standings.map((standing) => ({ ...standing }));
  }

  getRevision() {
    return this._revision;
  }

  getHistoryCursor() {
    return this._historyCursor;
  }

  getHistoryLength() {
    return this._history.length;
  }

  getLastTransition() {
    return this._historyCursor ? clone(this._history[this._historyCursor - 1]) : null;
  }

  getRedoTransition() {
    return this._historyCursor < this._history.length
      ? clone(this._history[this._historyCursor])
      : null;
  }

  getHistory() {
    return clone({ cursor: this._historyCursor, transitions: this._history });
  }

  getResolvableCells() {
    return this._buildResolvableCache().cells;
  }

  getResolvableCount() {
    return this._buildResolvableCache().cells.length;
  }

  getResolvableCellsForContestant(contestantId) {
    return this._buildResolvableCache().byContestant.get(String(contestantId)) ?? EMPTY_TARGETS;
  }

  getResolvableCellsForProblem(problemId) {
    return this._buildResolvableCache().byProblem.get(String(problemId)) ?? EMPTY_TARGETS;
  }

  _projectReveal(contestantId, problemId) {
    const normalizedProblemId = String(problemId);
    if (!this._problems.has(normalizedProblemId)) {
      throw new RangeError(
        gettext('Unknown Resolver problem "%(problem)s".', { problem: problemId }),
      );
    }

    const contestant = this._findContestant(contestantId);
    if (!contestant) {
      throw new RangeError(
        gettext('Unknown Resolver contestant "%(contestant)s".', { contestant: contestantId }),
      );
    }
    const currentCell = contestant.problems[normalizedProblemId];
    if (!this.adapter.isResolvable(currentCell)) {
      return null;
    }

    const beforeStanding = this._state.standings.find(
      (standing) => String(standing.contestantId) === String(contestant.participationId),
    );
    const topBefore = this._state.standings[0]?.contestantId ?? null;
    const beforeScore = contestant.score;
    const beforePoints = currentCell.points;

    const afterContestant = clone(contestant);
    afterContestant.problems[normalizedProblemId] = this.adapter.revealCell(
      afterContestant.problems[normalizedProblemId],
      this._finalCells[String(contestant.participationId)][normalizedProblemId],
    );
    this._recomputeContestant(afterContestant);
    const remainingResolvableCells = this.getResolvableCount() - 1;
    const projectedContestants = this._state.contestants.map((entry) =>
      String(entry.participationId) === String(afterContestant.participationId)
        ? afterContestant
        : entry,
    );
    const projectedStandings = rankContestants(projectedContestants, {
      fallback: remainingResolvableCells === 0 ? "finalOrder" : "tieKey",
    });

    const afterStanding = projectedStandings.find(
      (standing) => String(standing.contestantId) === String(contestant.participationId),
    );
    const revealedCell = afterContestant.problems[normalizedProblemId];
    const authoritativeFirstSolveId =
      this._problems.get(normalizedProblemId).first_solve_participation_id ?? null;
    const authoritativeFirstSolveAppeared =
      authoritativeFirstSolveId !== null &&
      String(authoritativeFirstSolveId) === String(contestant.participationId) &&
      revealedCell.state === "solved";
    const topAfter = projectedStandings[0]?.contestantId ?? null;

    return {
      id: null,
      type: "reveal-cell",
      revision: this._revision,
      target: {
        contestantId: contestant.participationId,
        problemId: this._problems.get(normalizedProblemId).id,
      },
      targets: [
        {
          contestantId: contestant.participationId,
          problemId: this._problems.get(normalizedProblemId).id,
        },
      ],
      changedCells: [
        {
          contestantId: contestant.participationId,
          problemId: this._problems.get(normalizedProblemId).id,
          beforeCell: clone(currentCell),
          afterCell: clone(revealedCell),
        },
      ],
      effects: {
        positionBefore: beforeStanding.position,
        positionAfter: afterStanding.position,
        rankBefore: beforeStanding.rank,
        rankAfter: afterStanding.rank,
        contestantFinished: this._isFullyResolved(afterContestant),
        topChanged: String(topBefore) !== String(topAfter),
        scoreImproved: afterContestant.score > beforeScore,
        cellPointsImproved: revealedCell.points > beforePoints,
        authoritativeFirstSolveAppeared,
        firstSolveAppeared: authoritativeFirstSolveAppeared,
        remainingResolvableCells,
      },
    };
  }

  projectReveal(contestantId, problemId) {
    return clone(this._projectReveal(contestantId, problemId));
  }

  _projectBatch(targets) {
    const uniqueTargets = [];
    const seen = new Set();
    for (const target of targets) {
      const contestant = this._findContestant(target.contestantId);
      if (!contestant) {
        throw new RangeError(
          gettext('Unknown Resolver contestant "%(contestant)s".', {
            contestant: target.contestantId,
          }),
        );
      }
      const normalizedProblemId = String(target.problemId);
      const problem = this._problems.get(normalizedProblemId);
      if (!problem) {
        throw new RangeError(
          gettext('Unknown Resolver problem "%(problem)s".', { problem: target.problemId }),
        );
      }
      const key = `${contestant.participationId}:${normalizedProblemId}`;
      if (seen.has(key) || !this.adapter.isResolvable(contestant.problems[normalizedProblemId])) {
        continue;
      }
      seen.add(key);
      uniqueTargets.push({ contestantId: contestant.participationId, problemId: problem.id });
    }
    if (!uniqueTargets.length) {
      return null;
    }

    const workingContestants = new Map();
    const changedCells = [];
    for (const target of uniqueTargets) {
      const contestantId = String(target.contestantId);
      const problemId = String(target.problemId);
      let contestant = workingContestants.get(contestantId);
      if (!contestant) {
        contestant = clone(this._findContestant(target.contestantId));
        workingContestants.set(contestantId, contestant);
      }
      const beforeCell = contestant.problems[problemId];
      const afterCell = this.adapter.revealCell(
        beforeCell,
        this._finalCells[contestantId][problemId],
      );
      contestant.problems[problemId] = afterCell;
      changedCells.push({
        contestantId: target.contestantId,
        problemId: target.problemId,
        beforeCell: clone(beforeCell),
        afterCell: clone(afterCell),
      });
    }
    workingContestants.forEach((contestant) => this._recomputeContestant(contestant));
    const remainingResolvableCells = this.getResolvableCount() - changedCells.length;
    const projectedContestants = this._state.contestants.map(
      (contestant) => workingContestants.get(String(contestant.participationId)) ?? contestant,
    );
    const projectedStandings = rankContestants(projectedContestants, {
      fallback: remainingResolvableCells === 0 ? "finalOrder" : "tieKey",
    });
    const beforeStandings = new Map(
      this._state.standings.map((standing) => [String(standing.contestantId), standing]),
    );
    const afterStandings = new Map(
      projectedStandings.map((standing) => [String(standing.contestantId), standing]),
    );
    const positionChanges = [...workingContestants].map(([contestantId, contestant]) => {
      const before = beforeStandings.get(contestantId);
      const after = afterStandings.get(contestantId);
      const source = this._findContestant(contestantId);
      return {
        contestantId: contestant.participationId,
        positionBefore: before.position,
        positionAfter: after.position,
        rankBefore: before.rank,
        rankAfter: after.rank,
        scoreImproved: contestant.score > source.score,
      };
    });
    return {
      id: null,
      type: changedCells.length === 1 ? "reveal-cell" : "reveal-batch",
      revision: this._revision,
      target: clone(uniqueTargets[0]),
      targets: clone(uniqueTargets),
      changedCells,
      effects: {
        batch: true,
        positionChanges,
        remainingResolvableCells,
      },
    };
  }

  _commitProjection(projection) {
    if (!projection) {
      return null;
    }
    if (projection.revision !== this._revision) {
      throw new Error(gettext("Resolver projection is stale and cannot be committed."));
    }
    if (this._historyCursor < this._history.length) {
      this._history.splice(this._historyCursor);
    }
    const affectedContestants = new Set();
    projection.changedCells.forEach((change) => {
      const contestant = this._findContestant(change.contestantId);
      contestant.problems[String(change.problemId)] = clone(change.afterCell);
      affectedContestants.add(String(change.contestantId));
    });
    affectedContestants.forEach((contestantId) =>
      this._recomputeContestant(this._findContestant(contestantId)),
    );
    this._rerank();
    const transition = {
      id: `reveal-${++this._transitionSerial}`,
      type: projection.type,
      target: clone(projection.target),
      targets: clone(projection.targets),
      changedCells: clone(projection.changedCells),
      effects: clone(projection.effects),
    };
    this._history.push(transition);
    this._historyCursor += 1;
    this._advanceRevision();
    return clone(transition);
  }

  commitProjection(projection) {
    return this._commitProjection(projection);
  }

  revealCell(contestantId, problemId) {
    return this._commitProjection(this._projectReveal(contestantId, problemId));
  }

  revealBatch(targets) {
    if (!Array.isArray(targets)) {
      throw new TypeError(gettext("Resolver batch targets must be an array."));
    }
    return this._commitProjection(this._projectBatch(targets));
  }

  _applyTransitionCells(transition, field) {
    const affectedContestants = new Set();
    transition.changedCells.forEach((change) => {
      const contestant = this._findContestant(change.contestantId);
      contestant.problems[String(change.problemId)] = clone(change[field]);
      affectedContestants.add(String(change.contestantId));
    });
    affectedContestants.forEach((contestantId) =>
      this._recomputeContestant(this._findContestant(contestantId)),
    );
    this._rerank();
    this._advanceRevision();
  }

  back() {
    if (this._historyCursor === 0) {
      return false;
    }
    this._historyCursor -= 1;
    this._applyTransitionCells(this._history[this._historyCursor], "beforeCell");
    return true;
  }

  forward() {
    if (this._historyCursor >= this._history.length) {
      return false;
    }
    this._applyTransitionCells(this._history[this._historyCursor], "afterCell");
    this._historyCursor += 1;
    return true;
  }

  reset() {
    this._state = clone(this._baselineState);
    this._history = [];
    this._historyCursor = 0;
    this._transitionSerial = 0;
    this._advanceRevision();
    return this.getState();
  }

  replay() {
    return this.reset();
  }
}
