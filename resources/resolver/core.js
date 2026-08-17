import { DefaultAdapter } from "./formats/default.js";
import { ICPCAdapter } from "./formats/icpc.js";
import { VNOJAdapter } from "./formats/vnoj.js";
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

export class UnsupportedResolverFormatError extends Error {
  constructor(formatName) {
    super(`Contest format "${formatName}" is not supported by Resolver.`);
    this.name = "UnsupportedResolverFormatError";
    this.formatName = formatName;
  }
}

export class UnsupportedResolverBaselineError extends Error {
  constructor(baseline) {
    super(`Resolver baseline "${baseline}" is not available for this contest.`);
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
    throw new TypeError("Invalid Resolver schema version 1 payload.");
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
  return {
    participationId: sourceContestant.participation_id,
    profileId: sourceContestant.profile_id,
    username: sourceContestant.username,
    displayName: sourceContestant.display_name,
    cssClass: sourceContestant.user_css_class,
    profileUrl: sourceContestant.profile_url,
    avatarUrl: sourceContestant.avatar_url,
    rankLogoUrl: sourceContestant.rank_logo_url,
    organization: clone(sourceContestant.organization),
    isDisqualified: sourceContestant.is_disqualified === true,
    submissionCount: sourceContestant.submission_count,
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
      throw new TypeError(`Unknown Resolver tie order "${this.tieOrder}".`);
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
    const tieKeys =
      this.tieOrder === "source"
        ? createSourceOrderTieKeys(this.source.contestants)
        : createDeterministicTieKeys(this.source.contestants, this.seed);
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

    return {
      contestants,
      standings: rankContestants(contestants),
    };
  }

  _findContestant(contestantId) {
    const normalized = String(contestantId);
    return this._state.contestants.find(
      (contestant) => String(contestant.participationId) === normalized,
    );
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

  _rerank() {
    this._state.standings = rankContestants(this._state.contestants);
  }

  getState() {
    return clone(this._state);
  }

  getHistory() {
    return clone({ cursor: this._historyCursor, transitions: this._history });
  }

  getResolvableCells() {
    const cells = [];
    this._state.contestants.forEach((contestant) => {
      this._orderedProblems.forEach((problem) => {
        const problemId = String(problem.id);
        if (this.adapter.isResolvable(contestant.problems[problemId])) {
          cells.push({
            contestantId: contestant.participationId,
            problemId: problem.id,
          });
        }
      });
    });
    return cells;
  }

  revealCell(contestantId, problemId) {
    const contestant = this._findContestant(contestantId);
    if (!contestant) {
      throw new RangeError(`Unknown Resolver contestant "${contestantId}".`);
    }
    const normalizedProblemId = String(problemId);
    if (!this._problems.has(normalizedProblemId)) {
      throw new RangeError(`Unknown Resolver problem "${problemId}".`);
    }

    const currentCell = contestant.problems[normalizedProblemId];
    if (!this.adapter.isResolvable(currentCell)) {
      return null;
    }

    if (this._historyCursor < this._history.length) {
      this._history.splice(this._historyCursor);
    }
    const before = clone(this._state);
    const beforeStanding = before.standings.find(
      (standing) => String(standing.contestantId) === String(contestant.participationId),
    );
    const firstSolveExisted = before.contestants.some(
      (entry) => entry.problems[normalizedProblemId]?.state === "solved",
    );
    const topBefore = before.standings[0]?.contestantId ?? null;

    contestant.problems[normalizedProblemId] = this.adapter.revealCell(
      currentCell,
      this._finalCells[String(contestant.participationId)][normalizedProblemId],
    );
    this._recomputeContestant(contestant);
    this._rerank();

    const after = clone(this._state);
    const afterStanding = after.standings.find(
      (standing) => String(standing.contestantId) === String(contestant.participationId),
    );
    const revealedCell = contestant.problems[normalizedProblemId];
    const topAfter = after.standings[0]?.contestantId ?? null;
    const transition = {
      id: `reveal-${++this._transitionSerial}`,
      type: "reveal-cell",
      target: {
        contestantId: contestant.participationId,
        problemId: this._problems.get(normalizedProblemId).id,
      },
      before,
      after,
      effects: {
        positionBefore: beforeStanding.position,
        positionAfter: afterStanding.position,
        rankBefore: beforeStanding.rank,
        rankAfter: afterStanding.rank,
        contestantFinished: this._isFullyResolved(contestant),
        topChanged: String(topBefore) !== String(topAfter),
        firstSolveAppeared: !firstSolveExisted && revealedCell.state === "solved",
      },
    };
    this._history.push(transition);
    this._historyCursor += 1;
    return clone(transition);
  }

  back() {
    if (this._historyCursor === 0) {
      return false;
    }
    this._historyCursor -= 1;
    this._state = clone(this._history[this._historyCursor].before);
    return true;
  }

  forward() {
    if (this._historyCursor >= this._history.length) {
      return false;
    }
    this._state = clone(this._history[this._historyCursor].after);
    this._historyCursor += 1;
    return true;
  }

  reset() {
    this._state = clone(this._baselineState);
    this._history = [];
    this._historyCursor = 0;
    this._transitionSerial = 0;
    return this.getState();
  }

  replay() {
    return this.reset();
  }
}
