export const SPEED_PRESETS = Object.freeze([
  Object.freeze({ label: "0.5×", speed: 0.5 }),
  Object.freeze({ label: "1×", speed: 1 }),
  Object.freeze({ label: "2×", speed: 2 }),
  Object.freeze({ label: "4×", speed: 4 }),
]);

export const CEREMONY_PRESETS = Object.freeze({
  icpc: Object.freeze({
    baseline: "auto",
    policy: "row-sweep",
    granularity: "cell",
    tieOrder: "seeded",
    speedIndex: 1,
    awardPlaces: 6,
    singleStepStartRank: 0,
    hardPauses: Object.freeze({
      singleStep: false,
      award: false,
      firstSolve: false,
    }),
  }),
  full: Object.freeze({
    baseline: "beginning",
    policy: "row-sweep",
    granularity: "cell",
    tieOrder: "seeded",
    speedIndex: 1,
    awardPlaces: 0,
    singleStepStartRank: 0,
    hardPauses: Object.freeze({
      singleStep: false,
      award: false,
      firstSolve: false,
    }),
  }),
  director: Object.freeze({
    baseline: "auto",
    policy: "manual",
    granularity: "cell",
    tieOrder: "seeded",
    speedIndex: 1,
    awardPlaces: 0,
    singleStepStartRank: 0,
    hardPauses: Object.freeze({
      singleStep: false,
      award: false,
      firstSolve: false,
    }),
  }),
});

export function clampSpeedIndex(index) {
  return Math.max(0, Math.min(SPEED_PRESETS.length - 1, Number(index) || 0));
}

export function normalizeAwardPlaces(value, contestantCount) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.min(parsed, Math.max(0, contestantCount));
}

export function normalizeSingleStepStartRank(value, contestantCount) {
  return normalizeAwardPlaces(value, contestantCount);
}
