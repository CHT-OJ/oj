import { performance } from "node:perf_hooks";

import { ResolverSession } from "../core.js";
import { RowSweepPolicy } from "../policies.js";
import { createSyntheticPayload } from "./synthetic.js";

const CASES = [
  [50, 10],
  [100, 12],
  [200, 12],
];
const SAMPLE_REVEALS = 24;

function elapsed(operation) {
  const start = performance.now();
  const value = operation();
  return { value, duration: performance.now() - start };
}

function round(value) {
  return Math.round(value * 1000) / 1000;
}

function runCase(contestantCount, problemCount) {
  globalThis.gc?.();
  const heapBefore = process.memoryUsage().heapUsed;
  const payload = createSyntheticPayload(contestantCount, problemCount);
  const session = new ResolverSession(payload, { baseline: "beginning", seed: "benchmark" });
  const policy = new RowSweepPolicy(payload.problems.map((problem) => problem.id));
  const totals = {
    selectTargetMs: 0,
    getResolvableCellsMs: 0,
    projectRevealMs: 0,
    commitRevealMs: 0,
    getHistoryMs: 0,
    getStateMs: 0,
  };

  for (let index = 0; index < SAMPLE_REVEALS; index += 1) {
    const cells = elapsed(() => session.getResolvableCells());
    totals.getResolvableCellsMs += cells.duration;
    const selected = elapsed(() => policy.select(session));
    totals.selectTargetMs += selected.duration;
    if (!selected.value) {
      break;
    }
    totals.projectRevealMs += elapsed(() =>
      session.projectReveal(selected.value.contestantId, selected.value.problemId),
    ).duration;
    totals.commitRevealMs += elapsed(() =>
      session.revealCell(selected.value.contestantId, selected.value.problemId),
    ).duration;
    totals.getHistoryMs += elapsed(() => session.getHistory()).duration;
    totals.getStateMs += elapsed(() => session.getState()).duration;
  }

  globalThis.gc?.();
  const heapAfter = process.memoryUsage().heapUsed;
  const history = session.getHistory();
  return {
    size: `${contestantCount}x${problemCount}`,
    samples: SAMPLE_REVEALS,
    averagesMs: Object.fromEntries(
      Object.entries(totals).map(([name, total]) => [name, round(total / SAMPLE_REVEALS)]),
    ),
    historyJsonBytes: Buffer.byteLength(JSON.stringify(history)),
    retainedHeapBytes: Math.max(0, heapAfter - heapBefore),
  };
}

console.log(JSON.stringify(CASES.map(([contestants, problems]) => runCase(contestants, problems)), null, 2));
