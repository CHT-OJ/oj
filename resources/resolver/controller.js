export const SPEED_PRESETS = Object.freeze([
  Object.freeze({ label: "0.5×", delayMs: 2400 }),
  Object.freeze({ label: "1×", delayMs: 1500 }),
  Object.freeze({ label: "1.5×", delayMs: 850 }),
  Object.freeze({ label: "2×", delayMs: 350 }),
]);

export const CEREMONY_PRESETS = Object.freeze({
  icpc: Object.freeze({
    baseline: "auto",
    policy: "bottom-up-sticky",
    granularity: "cell",
    tieOrder: "seeded",
    speedIndex: 1,
    pauseBeats: Object.freeze({
      rankChange: true,
      awardZone: true,
      contestantFinished: true,
      firstSolve: true,
    }),
  }),
  full: Object.freeze({
    baseline: "beginning",
    policy: "bottom-up-sticky",
    granularity: "cell",
    tieOrder: "seeded",
    speedIndex: 1,
    pauseBeats: Object.freeze({
      rankChange: true,
      awardZone: true,
      contestantFinished: true,
      firstSolve: true,
    }),
  }),
  director: Object.freeze({
    baseline: "auto",
    policy: "manual",
    granularity: "cell",
    tieOrder: "seeded",
    speedIndex: 1,
    pauseBeats: Object.freeze({
      rankChange: false,
      awardZone: false,
      contestantFinished: false,
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

export function getPauseReason(transitions, pauseBeats, awardPlaces) {
  for (const transition of transitions) {
    const effects = transition.effects;
    if (
      pauseBeats.awardZone &&
      awardPlaces > 0 &&
      effects.rankBefore > awardPlaces &&
      effects.rankAfter <= awardPlaces
    ) {
      return `Entered the top ${awardPlaces} award zone.`;
    }
    if (pauseBeats.rankChange && effects.rankBefore !== effects.rankAfter) {
      return `Rank changed from ${effects.rankBefore} to ${effects.rankAfter}.`;
    }
    if (pauseBeats.firstSolve && effects.firstSolveAppeared) {
      return "A first solve appeared.";
    }
    if (pauseBeats.contestantFinished && effects.contestantFinished) {
      return "Contestant fully resolved.";
    }
  }
  return null;
}

function createDelay(duration) {
  let timer = null;
  let resolveDelay = null;
  return {
    promise: new Promise((resolve) => {
      resolveDelay = resolve;
      timer = globalThis.setTimeout(resolve, duration);
    }),
    cancel() {
      if (timer !== null) {
        globalThis.clearTimeout(timer);
        timer = null;
        resolveDelay();
      }
    },
  };
}

export class AutoplayController {
  constructor({ step, onChange = () => {}, speedIndex = 1 }) {
    this.step = step;
    this.onChange = onChange;
    this.speedIndex = clampSpeedIndex(speedIndex);
    this.playing = false;
    this.pauseKind = "idle";
    this.pauseReason = null;
    this._runSerial = 0;
    this._delay = null;
  }

  getState() {
    return {
      playing: this.playing,
      pauseKind: this.pauseKind,
      pauseReason: this.pauseReason,
      speedIndex: this.speedIndex,
      speed: SPEED_PRESETS[this.speedIndex],
    };
  }

  setSpeed(index) {
    this.speedIndex = clampSpeedIndex(index);
    this.onChange(this.getState());
    return this.getState();
  }

  slower() {
    return this.setSpeed(this.speedIndex - 1);
  }

  faster() {
    return this.setSpeed(this.speedIndex + 1);
  }

  play() {
    if (this.playing) {
      return;
    }
    this.playing = true;
    this.pauseKind = null;
    this.pauseReason = null;
    const serial = ++this._runSerial;
    this.onChange(this.getState());
    void this._run(serial);
  }

  pause(reason = "Autoplay paused.", kind = "operator") {
    this.playing = false;
    this.pauseKind = kind;
    this.pauseReason = reason;
    this._runSerial += 1;
    if (this._delay) {
      this._delay.cancel();
      this._delay = null;
    }
    this.onChange(this.getState());
  }

  toggle() {
    if (this.playing) {
      this.pause();
    } else {
      this.play();
    }
  }

  async _run(serial) {
    while (this.playing && serial === this._runSerial) {
      const result = await this.step();
      if (!this.playing || serial !== this._runSerial) {
        return;
      }
      if (!result || result.complete) {
        this.pause("Resolver complete — final standings reached.", "complete");
        return;
      }
      if (result.pauseReason) {
        this.pause(result.pauseReason, "beat");
        return;
      }
      this._delay = createDelay(SPEED_PRESETS[this.speedIndex].delayMs);
      await this._delay.promise;
      this._delay = null;
    }
  }
}
