import assert from "node:assert/strict";
import test from "node:test";

import { ResolverPage } from "../page.js";
import { estimateServerNow, getResolverSnapshotStatus } from "../snapshot.js";

const generatedAt = "2026-08-29T12:00:00+07:00";
const contestEndTime = "2026-08-29T13:00:00+07:00";

function metadata(snapshotState, overrides = {}) {
  const ended = snapshotState !== "preview";
  const settled = snapshotState === "final";
  return {
    generated_at: ended ? "2026-08-29T14:00:00+07:00" : generatedAt,
    contest_end_time: contestEndTime,
    contest_ended_at_generation: ended,
    snapshot_state: snapshotState,
    in_progress_submission_count: snapshotState === "unsettled" ? 3 : 0,
    pretested_submission_count: 0,
    results_settled_at_generation: settled,
    ...overrides,
  };
}

function snapshotPage(status, contest = {}, { setupMode = "initial", session = null } = {}) {
  const classes = new Set();
  const page = Object.create(ResolverPage.prototype);
  page.payload = {
    contest: {
      in_progress_submission_count: 0,
      pretested_submission_count: 0,
      ...contest,
    },
  };
  page.session = session;
  page.setupMode = setupMode;
  page.nodes = {
    snapshotWarning: {
      dataset: {},
      classList: {
        toggle(name, enabled) {
          if (enabled) {
            classes.add(name);
          } else {
            classes.delete(name);
          }
        },
      },
    },
    snapshotMode: { textContent: "" },
    snapshotMessage: { textContent: "" },
    setupSubmit: { disabled: false },
    setupSubmitLabel: { textContent: "" },
    setupIntro: { textContent: "" },
  };
  page._snapshotStatus = () => status;
  return { page, classes };
}

test("a preview snapshot remains preview after estimated server time passes contest end", () => {
  assert.deepEqual(
    getResolverSnapshotStatus(metadata("preview"), Date.parse("2026-08-29T06:30:00Z")),
    {
      kind: "preview",
      verified: true,
      canStart: false,
      contestMayHaveEnded: true,
      remainingMs: 0,
    },
  );
});

test("a verified preview can start rehearsal before contest end", () => {
  assert.deepEqual(
    getResolverSnapshotStatus(metadata("preview"), Date.parse("2026-08-29T05:30:00Z")),
    {
      kind: "preview",
      verified: true,
      canStart: true,
      contestMayHaveEnded: false,
      remainingMs: 30 * 60 * 1000,
    },
  );
});

test("a server-authoritative final snapshot remains final regardless of simulated time", () => {
  assert.deepEqual(
    getResolverSnapshotStatus(metadata("final"), Date.parse("2026-08-28T00:00:00Z")),
    {
      kind: "final",
      verified: true,
      canStart: true,
      contestMayHaveEnded: false,
      remainingMs: null,
    },
  );
});

test("an unsettled post-contest snapshot cannot start", () => {
  assert.deepEqual(getResolverSnapshotStatus(metadata("unsettled")), {
    kind: "unsettled",
    verified: true,
    canStart: false,
    contestMayHaveEnded: false,
    remainingMs: null,
  });
});

test("legacy, malformed, or inconsistent safety metadata fails closed", () => {
  assert.deepEqual(getResolverSnapshotStatus({}), {
    kind: "unknown",
    verified: false,
    canStart: false,
    contestMayHaveEnded: null,
    remainingMs: null,
  });
  assert.deepEqual(getResolverSnapshotStatus(metadata("final", { generated_at: "invalid" })), {
    kind: "unknown",
    verified: false,
    canStart: false,
    contestMayHaveEnded: null,
    remainingMs: null,
  });
  assert.deepEqual(
    getResolverSnapshotStatus(
      metadata("final", {
        results_settled_at_generation: false,
        in_progress_submission_count: 1,
      }),
    ),
    {
      kind: "unknown",
      verified: false,
      canStart: false,
      contestMayHaveEnded: null,
      remainingMs: null,
    },
  );
});

test("server-relative time advances from generated_at using a monotonic clock", () => {
  assert.equal(estimateServerNow(generatedAt, 1_000, 31_000), Date.parse(generatedAt) + 30_000);
  assert.equal(estimateServerNow("invalid", 1_000, 31_000), null);
  assert.equal(estimateServerNow(generatedAt, 31_000, 1_000), null);
});

test("pretested-only unsettled metadata is verified and blocked", () => {
  assert.deepEqual(
    getResolverSnapshotStatus(
      metadata("unsettled", {
        in_progress_submission_count: 0,
        pretested_submission_count: 14,
      }),
    ),
    {
      kind: "unsettled",
      verified: true,
      canStart: false,
      contestMayHaveEnded: false,
      remainingMs: null,
    },
  );
});

test("preview without an informational clock remains verified but never becomes final", () => {
  assert.deepEqual(getResolverSnapshotStatus(metadata("preview")), {
    kind: "preview",
    verified: true,
    canStart: true,
    contestMayHaveEnded: false,
    remainingMs: null,
  });
});

test("a running preview remains visibly preview after contest end without replacing its session", () => {
  const existingSession = { cursor: 7, history: 7 };
  const { page, classes } = snapshotPage(
    {
      kind: "preview",
      verified: true,
      canStart: false,
      contestMayHaveEnded: true,
      remainingMs: 0,
    },
    {},
    { setupMode: "edit", session: existingSession },
  );

  page._renderSnapshotSafety();

  assert.equal(page.session, existingSession);
  assert.equal(page.nodes.snapshotMode.textContent, "Preview");
  assert.match(
    page.nodes.snapshotMessage.textContent,
    /remains a preview|cannot be used as final/i,
  );
  assert.equal(page.nodes.setupSubmit.disabled, false);
  assert.equal(page.nodes.snapshotWarning.dataset.snapshotState, "preview");
  assert.equal(classes.has("alert-warning"), true);
});

test("unsettled snapshot UI explains both blockers and disables initial Start", () => {
  const { page, classes } = snapshotPage(
    {
      kind: "unsettled",
      verified: true,
      canStart: false,
      contestMayHaveEnded: false,
      remainingMs: null,
    },
    { in_progress_submission_count: 3, pretested_submission_count: 14 },
  );

  page._renderSnapshotSafety();

  assert.equal(page.nodes.setupSubmit.disabled, true);
  assert.match(page.nodes.snapshotMessage.textContent, /3 submissions are still being judged/);
  assert.match(page.nodes.snapshotMessage.textContent, /14 submissions still contain pretest-only/);
  assert.equal(classes.has("alert-danger"), true);
});

test("verified final snapshot UI enables Start Resolver", () => {
  const { page, classes } = snapshotPage({
    kind: "final",
    verified: true,
    canStart: true,
    contestMayHaveEnded: false,
    remainingMs: null,
  });

  page._renderSnapshotSafety();

  assert.equal(page.nodes.setupSubmit.disabled, false);
  assert.equal(page.nodes.setupSubmitLabel.textContent, "Start Resolver");
  assert.equal(page.nodes.snapshotMode.textContent, "Final results ready");
  assert.equal(classes.has("alert-success"), true);
});

test("unsafe Start fails closed and moves focus to Refresh", () => {
  const page = Object.create(ResolverPage.prototype);
  let rendered = false;
  let focused = false;
  page.session = null;
  page._snapshotStatus = () => ({ kind: "unknown", verified: false, canStart: false });
  page._renderSnapshotSafety = () => {
    rendered = true;
  };
  page.nodes = {
    snapshotRefresh: {
      focus() {
        focused = true;
      },
    },
  };

  assert.equal(page._startFromSetup(), null);
  assert.equal(page.session, null);
  assert.equal(rendered, true);
  assert.equal(focused, true);
});
