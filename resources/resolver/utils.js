export function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

export function deepFreeze(value) {
  if (value === null || typeof value !== "object" || Object.isFrozen(value)) {
    return value;
  }
  Object.freeze(value);
  Object.values(value).forEach(deepFreeze);
  return value;
}

export function roundLikePython(value, digits = 0) {
  if (!Number.isFinite(value)) {
    throw new TypeError("Resolver metrics must be finite numbers.");
  }
  if (!Number.isInteger(digits) || digits < 0 || digits > 10) {
    throw new RangeError("Resolver score precision must be an integer between 0 and 10.");
  }

  const absolute = Math.abs(value);
  if (absolute === 0) {
    return value;
  }

  const buffer = new ArrayBuffer(8);
  const view = new DataView(buffer);
  view.setFloat64(0, absolute, false);
  const high = view.getUint32(0, false);
  const low = view.getUint32(4, false);
  const exponentBits = (high >>> 20) & 0x7ff;
  const fraction = (BigInt(high & 0xfffff) << 32n) | BigInt(low);
  const significand = exponentBits === 0 ? fraction : (1n << 52n) | fraction;
  const binaryExponent = exponentBits === 0 ? -1074 : exponentBits - 1075;
  const decimalFactor = 10n ** BigInt(digits);

  let numerator = significand * decimalFactor;
  let denominator = 1n;
  if (binaryExponent >= 0) {
    numerator <<= BigInt(binaryExponent);
  } else {
    denominator <<= BigInt(-binaryExponent);
  }

  let rounded = numerator / denominator;
  const remainder = numerator % denominator;
  const comparison = remainder * 2n - denominator;
  if (comparison > 0n || (comparison === 0n && rounded % 2n !== 0n)) {
    rounded += 1n;
  }

  const result = Number(rounded) / Number(decimalFactor);
  return value < 0 ? -result : result;
}

export function numeric(value, fallback = 0) {
  return value === null || value === undefined ? fallback : Number(value);
}

export function cellState(problem, raw, extra = {}) {
  if (raw === null) {
    return {
      state: "empty",
      points: 0,
      score: null,
      time: 0,
      tries: null,
      penalty: null,
      pending: 0,
      attempted: false,
      revealed: true,
      ...extra,
    };
  }

  const points = numeric(raw.points);
  let state = "failed";
  if (points === numeric(problem.max_score)) {
    state = "solved";
  } else if (points !== 0) {
    state = "partial";
  }

  return {
    state,
    points,
    score: points,
    time: numeric(raw.time),
    tries: raw.tries === undefined ? null : numeric(raw.tries),
    penalty: raw.penalty === undefined ? null : numeric(raw.penalty),
    pending: numeric(raw.pending),
    attempted: true,
    revealed: true,
    ...extra,
  };
}

export function hiddenCell() {
  return {
    state: "hidden",
    points: 0,
    score: null,
    time: 0,
    tries: null,
    penalty: null,
    pending: 0,
    attempted: true,
    revealed: false,
  };
}
