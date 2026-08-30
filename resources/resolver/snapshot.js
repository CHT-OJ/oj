const SNAPSHOT_STATES = new Set(["preview", "unsettled", "final"]);

function parseTimestamp(value) {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function isNonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

function unknownStatus() {
  return {
    kind: "unknown",
    verified: false,
    canStart: false,
    contestMayHaveEnded: null,
    remainingMs: null,
  };
}

export function estimateServerNow(generatedAt, monotonicAtLoad, monotonicNow) {
  const generatedAtMs = parseTimestamp(generatedAt);
  const started = Number(monotonicAtLoad);
  const current = Number(monotonicNow);
  if (
    generatedAtMs === null ||
    !Number.isFinite(started) ||
    !Number.isFinite(current) ||
    current < started
  ) {
    return null;
  }
  return generatedAtMs + (current - started);
}

export function getResolverSnapshotStatus(contest, estimatedServerNow = null) {
  const state = contest?.snapshot_state;
  const generatedAt = parseTimestamp(contest?.generated_at);
  const contestEndTime = parseTimestamp(contest?.contest_end_time);
  const endedAtGeneration = contest?.contest_ended_at_generation;
  const resultsSettled = contest?.results_settled_at_generation;
  const inProgressCount = contest?.in_progress_submission_count;
  const pretestedCount = contest?.pretested_submission_count;
  const failedJudgingCount = contest?.failed_judging_submission_count;

  if (
    !SNAPSHOT_STATES.has(state) ||
    generatedAt === null ||
    contestEndTime === null ||
    typeof endedAtGeneration !== "boolean" ||
    typeof resultsSettled !== "boolean" ||
    !isNonNegativeInteger(inProgressCount) ||
    !isNonNegativeInteger(pretestedCount) ||
    !isNonNegativeInteger(failedJudgingCount)
  ) {
    return unknownStatus();
  }

  const isPreview = state === "preview";
  const isUnsettled = state === "unsettled";
  const isFinal = state === "final";
  const metadataIsConsistent =
    (isPreview && !endedAtGeneration && !resultsSettled && generatedAt <= contestEndTime) ||
    (isUnsettled &&
      endedAtGeneration &&
      !resultsSettled &&
      generatedAt > contestEndTime &&
      inProgressCount + pretestedCount + failedJudgingCount > 0) ||
    (isFinal &&
      endedAtGeneration &&
      resultsSettled &&
      generatedAt > contestEndTime &&
      inProgressCount === 0 &&
      pretestedCount === 0 &&
      failedJudgingCount === 0);
  if (!metadataIsConsistent) {
    return unknownStatus();
  }

  const now = Number(estimatedServerNow);
  const hasEstimatedNow = estimatedServerNow !== null && Number.isFinite(now);
  const contestMayHaveEnded = isPreview && hasEstimatedNow ? now >= contestEndTime : false;
  return {
    kind: state,
    verified: true,
    canStart: isFinal || (isPreview && !contestMayHaveEnded),
    contestMayHaveEnded,
    remainingMs: isPreview && hasEstimatedNow ? Math.max(0, contestEndTime - now) : null,
  };
}
