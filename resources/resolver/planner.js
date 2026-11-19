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

  projectNext(session, planningContext = {}) {
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
    const isSingleStep = usesSingleStepTiming(effects.positionBefore, this.singleStepStartRank);
    const singleStepBoundary = Math.min(this.singleStepStartRank, this.payload.contestants.length);
    const entersSingleStepZone = isSingleStep && effects.positionBefore === singleStepBoundary;
    const isAwardZoneTarget = this.awardPlaces > 0 && effects.positionBefore <= this.awardPlaces;
    const entersAwardZone = isAwardZoneTarget && planningContext.awardZoneEntered !== true;
    const awardZoneStart =
      this.hardPauses.award && isAwardZoneTarget && planningContext.awardZoneEntered !== true;

    let hardPauseKind = null;
    let hardPauseReason = null;
    if (this.hardPauses.firstSolve && effects.authoritativeFirstSolveAppeared) {
      hardPauseKind = "first-solve";
      hardPauseReason = gettext("Authoritative first solve on problem %(problem)s.", {
        problem: problem?.label ?? target.problemId,
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
      isAwardZoneTarget,
      awardZoneStart,
      awardZoneStartReason: awardZoneStart
        ? gettext("The ceremony has reached the top %(rank)s award zone.", {
            rank: this.awardPlaces,
          })
        : null,
      authoritativeFirstSolve: effects.authoritativeFirstSolveAppeared,
      hardPauseKind,
      hardPauseReason,
      projection,
    };
  }

  planNext(session, planningContext = {}) {
    const metadata = this.projectNext(session, planningContext);
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
