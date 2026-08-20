import {
  RESOLUTION_STEP_TYPES,
  ScoreboardTiming,
  SingleStepTiming,
  usesSingleStepTiming,
} from "./timing.js";

function normalizeId(value) {
  return String(value);
}

function countResolvableCells(state) {
  return state.contestants.reduce(
    (total, contestant) =>
      total +
      Object.values(contestant.problems).filter((cell) => cell.attempted && !cell.revealed).length,
    0,
  );
}

export function classifyResolutionResult(transition) {
  if (transition.effects.positionAfter < transition.effects.positionBefore) {
    return RESOLUTION_STEP_TYPES.RESULT_MOVE;
  }
  if (transition.effects.scoreImproved || transition.effects.cellPointsImproved) {
    return RESOLUTION_STEP_TYPES.RESULT_STAY;
  }
  return RESOLUTION_STEP_TYPES.RESULT_FAILED;
}

function crossingBoundary(beforeRank, afterRank, boundary) {
  return boundary > 0 && beforeRank > boundary && afterRank <= boundary;
}

export class ResolutionPlanner {
  constructor({
    payload,
    targetSelector,
    singleStepStartRank = 0,
    awardPlaces = 0,
    hardPauses = {},
  }) {
    this.payload = payload;
    this.targetSelector = targetSelector;
    this.singleStepStartRank = Number.parseInt(singleStepStartRank, 10) || 0;
    this.awardPlaces = Number.parseInt(awardPlaces, 10) || 0;
    this.hardPauses = {
      singleStep: hardPauses.singleStep !== false,
      award: hardPauses.award !== false,
      firstSolve: hardPauses.firstSolve !== false,
    };
    this.scoreboardTiming = new ScoreboardTiming();
    this.singleStepTiming = new SingleStepTiming();
    this.contestants = new Map(
      payload.contestants.map((contestant) => [
        normalizeId(contestant.participation_id),
        contestant,
      ]),
    );
    this.problems = new Map(payload.problems.map((problem) => [normalizeId(problem.id), problem]));
  }

  projectNext(session) {
    const target = this.targetSelector(session);
    if (!target) {
      return null;
    }
    const projection = session.projectReveal(target.contestantId, target.problemId);
    if (!projection) {
      return null;
    }
    const contestant = this.contestants.get(normalizeId(target.contestantId));
    const problem = this.problems.get(normalizeId(target.problemId));
    const { effects } = projection;
    const resultType = classifyResolutionResult(projection);
    const isSingleStep = usesSingleStepTiming(effects.rankBefore, this.singleStepStartRank);
    const entersSingleStepZone = crossingBoundary(
      effects.rankBefore,
      effects.rankAfter,
      this.singleStepStartRank,
    );
    const entersAwardZone = crossingBoundary(
      effects.rankBefore,
      effects.rankAfter,
      this.awardPlaces,
    );

    let hardPauseKind = null;
    let hardPauseReason = null;
    if (this.hardPauses.firstSolve && effects.authoritativeFirstSolveAppeared) {
      hardPauseKind = "first-solve";
      hardPauseReason = `Authoritative first solve on problem ${
        problem?.label ?? target.problemId
      }.`;
    } else if (this.hardPauses.award && entersAwardZone) {
      hardPauseKind = "award-boundary";
      hardPauseReason = `Entered the top ${this.awardPlaces} award zone.`;
    } else if (this.hardPauses.singleStep && entersSingleStepZone) {
      hardPauseKind = "single-step-boundary";
      hardPauseReason = `Entered the top ${this.singleStepStartRank} single-step region.`;
    }

    return {
      target: {
        contestantId: target.contestantId,
        problemId: target.problemId,
      },
      contestantLabel:
        contestant?.display_name || contestant?.username || String(target.contestantId),
      problemLabel: problem?.label ?? String(target.problemId),
      currentPosition: effects.positionBefore,
      currentRank: effects.rankBefore,
      actualPositionAfterReveal: effects.positionAfter,
      actualRankAfterReveal: effects.rankAfter,
      movementDelta: effects.positionBefore - effects.positionAfter,
      remainingUnresolvedCells: countResolvableCells(projection.after),
      resultType,
      isSingleStep,
      entersSingleStepZone,
      entersAwardZone,
      authoritativeFirstSolve: effects.authoritativeFirstSolveAppeared,
      hardPauseKind,
      hardPauseReason,
      projection,
    };
  }

  planNext(session) {
    const metadata = this.projectNext(session);
    if (!metadata) {
      return null;
    }
    const timing = metadata.isSingleStep ? this.singleStepTiming : this.scoreboardTiming;
    return {
      target: metadata.target,
      metadata,
      timing: metadata.isSingleStep ? "single-step" : "scoreboard",
      steps: timing.buildSteps(metadata),
    };
  }
}
