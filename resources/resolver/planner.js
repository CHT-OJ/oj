import {
  RESOLUTION_STEP_TYPES,
  ScoreboardTiming,
  SingleStepTiming,
  usesSingleStepTiming,
} from "./timing.js";
import { gettext } from "./i18n.js";

function normalizeId(value) {
  return String(value);
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
      singleStep: hardPauses.singleStep === true,
      award: hardPauses.award === true,
      firstSolve: hardPauses.firstSolve === true,
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
      hardPauseReason = gettext("Authoritative first solve on problem %(problem)s.", {
        problem: problem?.label ?? target.problemId,
      });
    } else if (this.hardPauses.award && entersAwardZone) {
      hardPauseKind = "award-boundary";
      hardPauseReason = gettext("Entered the top %(rank)s award zone.", {
        rank: this.awardPlaces,
      });
    } else if (this.hardPauses.singleStep && entersSingleStepZone) {
      hardPauseKind = "single-step-boundary";
      hardPauseReason = gettext("Entered the top %(rank)s single-step region.", {
        rank: this.singleStepStartRank,
      });
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
      remainingUnresolvedCells: effects.remainingResolvableCells,
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
