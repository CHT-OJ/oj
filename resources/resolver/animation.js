function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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

export async function animateChangedCells(tableBody, targets, duration = 560) {
  if (!targets.length || prefersReducedMotion()) {
    return;
  }
  const targetKeys = new Set(targets.map((target) => `${target.contestantId}:${target.problemId}`));
  const cells = [...tableBody.querySelectorAll("td[data-problem-id]")].filter((cell) =>
    targetKeys.has(`${cell.closest("tr").dataset.contestantId}:${cell.dataset.problemId}`),
  );
  await Promise.all(
    cells.map((cell) => {
      cell.classList.add("resolver-cell--changed");
      return transitionPromise(cell, duration, "animationend").then(() =>
        cell.classList.remove("resolver-cell--changed"),
      );
    }),
  );
}
