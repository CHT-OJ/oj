export function prefersReducedMotion() {
  return Boolean(
    globalThis.window?.matchMedia &&
      globalThis.window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
}

function transitionPromise(element, duration, eventName) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      element.removeEventListener(eventName, finish);
      resolve();
    };
    element.addEventListener(eventName, finish, { once: true });
    window.setTimeout(finish, duration + 100);
  });
}

export function captureRowPositions(tableBody) {
  return new Map(
    [...tableBody.querySelectorAll("tr[data-contestant-id]")].map((row) => [
      row.dataset.contestantId,
      row.getBoundingClientRect().top,
    ]),
  );
}

export async function animateRows(tableBody, previousPositions, duration = 700) {
  if (!previousPositions.size || prefersReducedMotion()) {
    return;
  }

  const movingRows = [...tableBody.querySelectorAll("tr[data-contestant-id]")]
    .map((row) => {
      const previousTop = previousPositions.get(row.dataset.contestantId);
      if (previousTop === undefined) {
        return null;
      }
      const delta = previousTop - row.getBoundingClientRect().top;
      return Math.abs(delta) < 1 ? null : { row, delta };
    })
    .filter(Boolean);

  movingRows.forEach(({ row, delta }) => {
    row.style.transition = "none";
    row.style.transform = `translateY(${delta}px)`;
  });
  if (!movingRows.length) {
    return;
  }

  tableBody.getBoundingClientRect();
  await new Promise((resolve) =>
    window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)),
  );
  const completions = movingRows.map(({ row }) => {
    row.classList.add("resolver-row--moving");
    row.style.transition = `transform ${duration}ms cubic-bezier(0.22, 1, 0.36, 1)`;
    row.style.transform = "";
    return transitionPromise(row, duration, "transitionend").then(() => {
      row.classList.remove("resolver-row--moving");
      row.style.removeProperty("transition");
      row.style.removeProperty("transform");
    });
  });
  await Promise.all(completions);
}

function waitFor(durationMs) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, durationMs));
}

export function revealHighlightTargets(rowElements, targets) {
  const rows = new Map();
  const cells = new Map();
  targets.forEach((target) => {
    const contestantId = String(target.contestantId);
    const problemId = String(target.problemId);
    const row = rowElements.get(contestantId);
    if (!row) {
      return;
    }
    rows.set(contestantId, row);
    const cell = row._resolverRefs?.problemCells?.get(problemId);
    if (cell) {
      cells.set(`${contestantId}:${problemId}`, cell);
    }
  });
  return { rows: [...rows.values()], cells: [...cells.values()] };
}

export async function animateRevealHighlight(
  rowElements,
  targets,
  duration = 500,
  { subtleRows = false, reducedMotion = prefersReducedMotion(), wait = waitFor } = {},
) {
  const durationMs = Number(duration);
  if (!targets.length || !Number.isFinite(durationMs) || durationMs <= 0 || reducedMotion) {
    return { rows: 0, cells: 0 };
  }
  const affected = revealHighlightTargets(rowElements, targets);
  const rowClass = subtleRows
    ? "resolver-row--reveal-highlight-subtle"
    : "resolver-row--reveal-highlight";
  [...affected.rows, ...affected.cells].forEach((node) => {
    node.style.setProperty("--resolver-reveal-highlight-duration", `${durationMs}ms`);
  });
  affected.rows.forEach((row) => row.classList.add(rowClass));
  affected.cells.forEach((cell) => cell.classList.add("resolver-cell--reveal-highlight"));
  await wait(durationMs);
  affected.rows.forEach((row) => {
    row.classList.remove(rowClass);
    row.style.removeProperty("--resolver-reveal-highlight-duration");
  });
  affected.cells.forEach((cell) => {
    cell.classList.remove("resolver-cell--reveal-highlight");
    cell.style.removeProperty("--resolver-reveal-highlight-duration");
  });
  return { rows: affected.rows.length, cells: affected.cells.length };
}

export function isRowWithinSafeViewport(rect, viewportHeight, safeBand = 0.15) {
  const height = Number(viewportHeight);
  if (!rect || !Number.isFinite(height) || height <= 0) {
    return true;
  }
  const margin = Math.max(0, Math.min(0.45, Number(safeBand) || 0)) * height;
  return rect.top >= margin && rect.bottom <= height - margin;
}

export function ensureRowVisible(
  row,
  {
    viewportHeight = globalThis.window?.innerHeight ?? 0,
    behavior = "smooth",
    safeBand = 0.15,
  } = {},
) {
  if (!row || typeof row.getBoundingClientRect !== "function") {
    return false;
  }
  if (isRowWithinSafeViewport(row.getBoundingClientRect(), viewportHeight, safeBand)) {
    return false;
  }
  row.scrollIntoView({ block: "center", behavior });
  return true;
}
