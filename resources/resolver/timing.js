import { gettext } from "./i18n.js";

export const RESOLUTION_STEP_TYPES = Object.freeze({
  SCROLL_ROW: "SCROLL_ROW",
  SELECT_TEAM: "SELECT_TEAM",
  SELECT_PROBLEM: "SELECT_PROBLEM",
  SELECT_SUBMISSION: "SELECT_SUBMISSION",
  REVEAL_CELL: "REVEAL_CELL",
  RESULT_MOVE: "RESULT_MOVE",
  RESULT_STAY: "RESULT_STAY",
  RESULT_FAILED: "RESULT_FAILED",
  DESELECT: "DESELECT",
  DELAY: "DELAY",
  PAUSE: "PAUSE",
});

export const ICPC_EVENT_DELAYS_MS = Object.freeze({
  SELECT_TEAM: 1300,
  SELECT_PROBLEM: 1000,
  RESULT_MOVE: 2250,
  RESULT_STAY: 1500,
  RESULT_FAILED: 850,
  DESELECT: 250,
  SELECT_SUBMISSION: 450,
});

export function effectiveDelay(baseDelay, playbackSpeed) {
  const speed = Number(playbackSpeed);
  if (!Number.isFinite(speed) || speed <= 0) {
    throw new RangeError(gettext("Resolver playback speed must be greater than zero."));
  }
  return Number(baseDelay) / speed;
}

function action(type, metadata) {
  return { type, ...metadata };
}

function delay(afterType) {
  return action(RESOLUTION_STEP_TYPES.DELAY, {
    afterType,
    durationMs: ICPC_EVENT_DELAYS_MS[afterType],
  });
}

function pause(kind, reason, hard = false) {
  return action(RESOLUTION_STEP_TYPES.PAUSE, { kind, reason, hard });
}

function stepDetails(metadata) {
  return {
    target: metadata.target,
    contestantLabel: metadata.contestantLabel,
    problemLabel: metadata.problemLabel,
    currentPosition: metadata.currentPosition,
    actualPositionAfterReveal: metadata.actualPositionAfterReveal,
    movementDelta: metadata.movementDelta,
  };
}

function commonPrefix(metadata) {
  const details = stepDetails(metadata);
  return [
    action(RESOLUTION_STEP_TYPES.SCROLL_ROW, details),
    action(RESOLUTION_STEP_TYPES.SELECT_TEAM, details),
  ];
}

export class ScoreboardTiming {
  buildSteps(metadata) {
    const details = stepDetails(metadata);
    const steps = [
      ...commonPrefix(metadata),
      delay(RESOLUTION_STEP_TYPES.SELECT_TEAM),
      action(RESOLUTION_STEP_TYPES.SELECT_PROBLEM, details),
      delay(RESOLUTION_STEP_TYPES.SELECT_PROBLEM),
      action(RESOLUTION_STEP_TYPES.REVEAL_CELL, details),
      action(metadata.resultType, details),
      delay(metadata.resultType),
    ];
    if (metadata.hardPauseReason) {
      steps.push(pause(metadata.hardPauseKind, metadata.hardPauseReason, true));
    }
    steps.push(
      action(RESOLUTION_STEP_TYPES.DESELECT, details),
      delay(RESOLUTION_STEP_TYPES.DESELECT),
    );
    return steps;
  }
}

export class SingleStepTiming {
  buildSteps(metadata) {
    const details = stepDetails(metadata);
    return [
      ...commonPrefix(metadata),
      pause(
        "single-step-team",
        gettext("Selected %(contestant)s.", { contestant: metadata.contestantLabel }),
      ),
      action(RESOLUTION_STEP_TYPES.SELECT_PROBLEM, details),
      pause(
        "single-step-problem",
        gettext("Selected problem %(problem)s.", { problem: metadata.problemLabel }),
      ),
      action(RESOLUTION_STEP_TYPES.REVEAL_CELL, details),
      action(metadata.resultType, details),
      pause(
        metadata.hardPauseKind ?? "single-step-result",
        metadata.hardPauseReason ??
          gettext("Revealed problem %(problem)s.", { problem: metadata.problemLabel }),
        Boolean(metadata.hardPauseReason),
      ),
      action(RESOLUTION_STEP_TYPES.DESELECT, details),
    ];
  }
}

export function usesSingleStepTiming(displayedRank, singleStepStartRank) {
  const threshold = Number.parseInt(singleStepStartRank, 10);
  return Number.isFinite(threshold) && threshold > 0 && displayedRank <= threshold;
}
