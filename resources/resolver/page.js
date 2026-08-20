import { animateChangedCells, animateRows, captureRowPositions } from "./animation.js";
import {
  CEREMONY_PRESETS,
  SPEED_PRESETS,
  clampSpeedIndex,
  normalizeAwardPlaces,
  normalizeSingleStepStartRank,
} from "./controller.js";
import { ResolverSession } from "./core.js";
import { gettext, ngettext } from "./i18n.js";
import { ResolutionPlanner } from "./planner.js";
import { ResolutionPlayer } from "./player.js";
import {
  BottomUpStickyPolicy,
  ByContestantPolicy,
  ByProblemPolicy,
  RowSweepPolicy,
} from "./policies.js";
import {
  deriveProblemStats,
  getCellPresentation,
  getMetricPresentation,
  getOrganizationPresentation,
  normalizeRankDisplayOption,
} from "./presentation.js";
import { RESOLUTION_STEP_TYPES } from "./timing.js";

function element(tagName, className = "", text = null) {
  const node = document.createElement(tagName);
  if (className) {
    node.className = className;
  }
  if (text !== null) {
    node.textContent = text;
  }
  return node;
}

function normalizedId(value) {
  return String(value);
}

function isTypingTarget(target) {
  return (
    target instanceof HTMLElement &&
    (target.matches("input, textarea, select") || target.isContentEditable)
  );
}

function setIconLabel(button, iconName, label) {
  const icon = element("i", `fa ${iconName}`);
  button.replaceChildren(icon, document.createTextNode(` ${label}`));
}

const POLICY_LABELS = Object.freeze({
  "row-sweep": gettext("ICPC ceremony"),
  "bottom-up-sticky": gettext("Bottom-up"),
  "by-problem": gettext("By problem"),
  "by-contestant": gettext("By contestant"),
  manual: gettext("Manual"),
});

export class ResolverPage {
  constructor(root, payload) {
    this.root = root;
    this.payload = payload;
    this.problems = [...payload.problems].sort(
      (left, right) => left.order - right.order || String(left.id).localeCompare(String(right.id)),
    );
    this.session = null;
    this.policy = new RowSweepPolicy(this.problems.map((problem) => problem.id));
    this.policyName = "row-sweep";
    this.hardPauses = { ...CEREMONY_PRESETS.icpc.hardPauses };
    this.awardPlaces = Math.min(6, payload.contestants.length);
    this.singleStepStartRank = 0;
    this.speedIndex = 1;
    this.planner = null;
    this.player = null;
    this.busy = false;
    this.totalResolvable = 0;
    this.hudVisible = false;
    this.statusMessage = gettext("Ready to start Resolver.");
    this.helpReturnFocus = null;
    this.projectionCache = null;
    this.problemHeaderButtons = new Map();
    this.rowElements = new Map();
    this.totalRow = null;

    this.nodes = {
      setup: root.querySelector("#resolver-setup"),
      setupForm: root.querySelector("#resolver-setup-form"),
      baseline: root.querySelector("#resolver-baseline"),
      policy: root.querySelector("#resolver-policy"),
      granularity: root.querySelector("#resolver-granularity"),
      tieOrder: root.querySelector("#resolver-tie-order"),
      speed: root.querySelector("#resolver-speed"),
      autoplay: root.querySelector("#resolver-autoplay"),
      awardPlaces: root.querySelector("#resolver-award-places"),
      singleStepStartRank: root.querySelector("#resolver-single-step-start-rank"),
      pauseAward: root.querySelector('[name="pause_award"]'),
      pauseFirstSolve: root.querySelector('[name="pause_first_solve"]'),
      freezeNote: root.querySelector("#resolver-freeze-note"),
      workspace: root.querySelector("#resolver-workspace"),
      table: root.querySelector("#ranking-table"),
      tableHead: root.querySelector("#resolver-table-head"),
      tableBody: root.querySelector("#resolver-table-body"),
      status: root.querySelector("#resolver-status"),
      progress: root.querySelector("#resolver-progress"),
      next: root.querySelector("#resolver-next"),
      play: root.querySelector("#resolver-play"),
      slower: root.querySelector("#resolver-slower"),
      faster: root.querySelector("#resolver-faster"),
      speedLabel: root.querySelector("#resolver-speed-label"),
      back: root.querySelector("#resolver-back"),
      forward: root.querySelector("#resolver-forward"),
      reset: root.querySelector("#resolver-reset"),
      replay: root.querySelector("#resolver-replay"),
      toggleHud: root.querySelector("#resolver-toggle-hud"),
      help: root.querySelector("#resolver-help"),
      fullscreen: root.querySelector("#resolver-fullscreen"),
      changeSetup: root.querySelector("#resolver-change-setup"),
      hud: root.querySelector("#resolver-hud"),
      hudMode: root.querySelector("#resolver-hud-mode"),
      hudTarget: root.querySelector("#resolver-hud-target"),
      hudHistory: root.querySelector("#resolver-hud-history"),
      hudAward: root.querySelector("#resolver-hud-award"),
      hudCurrentPosition: root.querySelector("#resolver-hud-current-position"),
      hudAfterPosition: root.querySelector("#resolver-hud-after-position"),
      hudMovement: root.querySelector("#resolver-hud-movement"),
      hudZone: root.querySelector("#resolver-hud-zone"),
      hudRemaining: root.querySelector("#resolver-hud-remaining"),
      hudSeed: root.querySelector("#resolver-hud-seed"),
      shortcuts: root.querySelector("#resolver-shortcuts"),
      shortcutsClose: root.querySelector("#resolver-shortcuts-close"),
    };
  }

  mount() {
    this._configureSetup();
    this._applyPreset("icpc");
    this._bindEvents();
    this.nodes.setup.hidden = false;
    this.nodes.workspace.hidden = true;
  }

  _configureSetup() {
    const freezeAvailable = this.payload.contest.official_freeze_available;
    const autoOption = this.nodes.baseline.querySelector('option[value="auto"]');
    const freezeOption = this.nodes.baseline.querySelector('option[value="official-freeze"]');
    autoOption.textContent = freezeAvailable
      ? gettext("Auto (official freeze)")
      : gettext("Auto (beginning)");
    freezeOption.disabled = !freezeAvailable;
    this.nodes.awardPlaces.max = String(this.payload.contestants.length);
    this.nodes.awardPlaces.value = String(this.awardPlaces);
    this.nodes.singleStepStartRank.max = String(this.payload.contestants.length);
    this.nodes.singleStepStartRank.value = String(this.singleStepStartRank);
    this.nodes.freezeNote.textContent = freezeAvailable
      ? gettext("Official freeze — %(minutes)s min", {
          minutes: this.payload.contest.frozen_last_minutes,
        })
      : gettext("Beginning");
  }

  _bindEvents() {
    this.nodes.setupForm.addEventListener("submit", (event) => {
      event.preventDefault();
      this._start();
    });
    this.nodes.next.addEventListener("click", () => void this._playToNextPause(true));
    this.nodes.play.addEventListener("click", () => this._togglePlayback());
    this.nodes.slower.addEventListener("click", () => this._changeSpeed(-1));
    this.nodes.faster.addEventListener("click", () => this._changeSpeed(1));
    this.nodes.back.addEventListener("click", () => {
      this._pausePlayback();
      if (this.policyName === "manual") {
        void this._moveHistory("back");
      } else {
        void this.player?.rewindToPreviousPause();
      }
    });
    this.nodes.forward.addEventListener("click", () => {
      if (this.policyName === "manual") {
        void this._moveHistory("forward");
      } else {
        void this._playToNextPause(false);
      }
    });
    this.nodes.reset.addEventListener("click", () => {
      this._pausePlayback();
      void this._reset(false);
    });
    this.nodes.replay.addEventListener("click", () => void this._replay());
    this.nodes.toggleHud.addEventListener("click", () => this._toggleHud());
    this.nodes.help.addEventListener("click", () => this._showShortcuts());
    this.nodes.shortcutsClose.addEventListener("click", () => this._hideShortcuts());
    this.nodes.shortcuts.addEventListener("click", (event) => {
      if (event.target === this.nodes.shortcuts) {
        this._hideShortcuts();
      }
    });
    this.nodes.fullscreen.addEventListener("click", () => void this._toggleFullscreen());
    this.nodes.changeSetup.addEventListener("click", () => this._showSetup());
    this.nodes.tableBody.addEventListener("click", (event) => {
      const action = event.target.closest("[data-resolver-action]");
      if (!action || event.target.closest("a") || this.busy) {
        return;
      }
      this._pausePlayback(gettext("Playback paused for a manual reveal."));
      this.policy.clear();
      if (action.dataset.resolverAction === "reveal-cell") {
        void this._revealTargets(
          [
            {
              contestantId: action.dataset.contestantId,
              problemId: action.dataset.problemId,
            },
          ],
          gettext("Manual cell reveal"),
        );
      } else if (action.dataset.resolverAction === "reveal-contestant") {
        void this._revealContestant(
          action.dataset.contestantId,
          gettext("Reveal all results for this contestant"),
        );
      }
    });
    this.nodes.tableBody.addEventListener("keydown", (event) => {
      const action = event.target.closest('[data-resolver-action="reveal-contestant"]');
      if (action && !event.target.closest("a") && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        action.click();
      }
    });
    this.nodes.tableHead.addEventListener("click", (event) => {
      const action = event.target.closest('[data-resolver-action="reveal-problem"]');
      if (!action || this.busy || action.disabled) {
        return;
      }
      this._pausePlayback(gettext("Playback paused for a manual reveal."));
      this.policy.clear();
      const problem = this.problems.find(
        (entry) => normalizedId(entry.id) === normalizedId(action.dataset.problemId),
      );
      void this._revealProblem(
        action.dataset.problemId,
        gettext("Reveal problem %(problem)s", {
          problem: problem?.label ?? action.dataset.problemId,
        }),
      );
    });
    this.nodes.tableHead.addEventListener("keydown", (event) => {
      const action = event.target.closest('[data-resolver-action="reveal-problem"]');
      if (action && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        action.click();
      }
    });
    document.addEventListener("keydown", (event) => this._handleShortcut(event));
    document.addEventListener("fullscreenchange", () => this._renderControls());
  }

  _applyPreset(name) {
    const preset = CEREMONY_PRESETS[name];
    if (!preset) {
      return;
    }
    this.nodes.baseline.value = preset.baseline;
    this.nodes.policy.value = preset.policy;
    this.nodes.granularity.value = preset.granularity;
    this.nodes.tieOrder.value = preset.tieOrder;
    this.nodes.speed.value = String(preset.speedIndex);
    this.nodes.awardPlaces.value = String(
      Math.min(preset.awardPlaces, this.payload.contestants.length),
    );
    this.nodes.singleStepStartRank.value = String(
      Math.min(preset.singleStepStartRank, this.payload.contestants.length),
    );
    this.nodes.pauseAward.checked = preset.hardPauses.award;
    this.nodes.pauseFirstSolve.checked = preset.hardPauses.firstSolve;
    this.speedIndex = preset.speedIndex;
    this.player?.setSpeed(SPEED_PRESETS[this.speedIndex].speed);
  }

  _start() {
    this._pausePlayback();
    try {
      this.session = new ResolverSession(this.payload, {
        baseline: this.nodes.baseline.value,
        tieOrder: this.nodes.tieOrder.value,
      });
    } catch (error) {
      this.nodes.freezeNote.textContent = gettext("Resolver could not start: %(error)s", {
        error: error.message,
      });
      return;
    }

    this.policyName = this.nodes.policy.value;
    this.policy = this._createPolicy(this.policyName);
    this.awardPlaces = normalizeAwardPlaces(
      this.nodes.awardPlaces.value,
      this.payload.contestants.length,
    );
    this.nodes.awardPlaces.value = String(this.awardPlaces);
    this.singleStepStartRank = normalizeSingleStepStartRank(
      this.nodes.singleStepStartRank.value,
      this.payload.contestants.length,
    );
    this.nodes.singleStepStartRank.value = String(this.singleStepStartRank);
    this.hardPauses = {
      singleStep: this.singleStepStartRank > 0,
      award: this.nodes.pauseAward.checked,
      firstSolve: this.nodes.pauseFirstSolve.checked,
    };
    this.speedIndex = clampSpeedIndex(Number(this.nodes.speed.value));
    this.planner = new ResolutionPlanner({
      payload: this.payload,
      targetSelector: (session) => this.policy.select(session),
      singleStepStartRank: this.singleStepStartRank,
      awardPlaces: this.awardPlaces,
      hardPauses: this.hardPauses,
    });
    this.player =
      this.policyName === "manual"
        ? null
        : new ResolutionPlayer({
            session: this.session,
            planner: this.planner,
            playbackSpeed: SPEED_PRESETS[this.speedIndex].speed,
            onBeforeStep: (step) => this._beforePlayerStep(step),
            onStep: (step, context) => this._performPlayerStep(step, context),
            onRestore: () => this._restorePlayerView(),
            onChange: (state) => this._onPlayerChange(state),
          });
    this.totalResolvable = this.session.getResolvableCount();
    this.projectionCache = null;
    this.statusMessage = gettext("Started from %(baseline)s.", {
      baseline: this._baselineLabel(),
    });
    this.nodes.setup.hidden = true;
    this.nodes.workspace.hidden = false;
    window.CHTOJResolverSession = this.session;
    this.rowElements.clear();
    this.totalRow = null;
    this.nodes.tableBody.replaceChildren();
    this._renderTableHead();
    this._render();
    if (this.nodes.autoplay.checked && this.player && this.session.getResolvableCount()) {
      void this.player.playContinuous(true);
    }
  }

  _createPolicy(name) {
    if (name === "row-sweep") {
      return new RowSweepPolicy(
        this.problems.map((problem) => problem.id),
        this.payload.contest.predetermined_problem_choices ?? {},
      );
    }
    if (name === "by-problem") {
      return new ByProblemPolicy(this.problems.map((problem) => problem.id));
    }
    if (name === "by-contestant") {
      return new ByContestantPolicy();
    }
    return new BottomUpStickyPolicy();
  }

  _showSetup() {
    if (this.busy) {
      return;
    }
    this._pausePlayback();
    this.nodes.workspace.hidden = true;
    this.nodes.setup.hidden = false;
    this.nodes.baseline.focus();
  }

  _baselineLabel() {
    return this.session.baseline === "official-freeze"
      ? gettext("official freeze")
      : gettext("the beginning");
  }

  _renderTableHead() {
    const formatName = this.payload.contest.format;
    const metrics = getMetricPresentation(formatName, { score: 0, cumtime: 0 });
    const labels = this.root.dataset;
    const row = element("tr");
    const coreHeaders = [
      { label: labels.labelRank || gettext("Rank"), className: "header rank" },
      { label: labels.labelUsername || gettext("Username"), className: "header username" },
      { label: labels.labelScore || metrics.scoreLabel, className: "header points" },
    ];
    if (formatName === "icpc") {
      coreHeaders.push({
        label: labels.labelPenalty || metrics.timeLabel,
        className: "header penalty",
      });
    }
    coreHeaders.forEach(({ label, className }) => {
      const header = element("th", `resolver-heading ${className}`, label);
      header.scope = "col";
      row.append(header);
    });
    this.problemHeaderButtons.clear();
    this.problems.forEach((problem) => {
      const header = element("th", "resolver-heading resolver-heading--problem header points");
      header.scope = "col";
      const button = element("button", "resolver-problem-header__button");
      button.type = "button";
      button.dataset.resolverAction = "reveal-problem";
      button.dataset.problemId = problem.id;
      button.title = gettext("Reveal all results for problem %(problem)s", {
        problem: problem.label,
      });
      button.setAttribute("aria-label", button.title);
      button.append(element("span", "resolver-problem-label", problem.label));
      if (formatName !== "icpc") {
        button.append(
          element(
            "span",
            "resolver-problem-denominator point-denominator",
            String(problem.max_score),
          ),
        );
      }
      const problemCode = element("span", "problem-code", problem.code);
      problemCode.hidden = true;
      button.append(problemCode);
      header.title = `${problem.code} — ${problem.name}`;
      header.append(button);
      this.problemHeaderButtons.set(normalizedId(problem.id), button);
      row.append(header);
    });
    this.nodes.tableHead.replaceChildren(row);
  }

  _render() {
    if (!this.session) {
      return;
    }
    const state = this.session.getState();
    const contestants = new Map(
      state.contestants.map((contestant) => [normalizedId(contestant.participationId), contestant]),
    );
    const stats = deriveProblemStats(this.payload, state);
    const statsByProblem = new Map(stats.map((stat) => [normalizedId(stat.problemId), stat]));
    const presentation = this.player?.getState().presentation ?? {};
    const activeSelection = presentation.selectedContestantId
      ? {
          contestantId: presentation.selectedContestantId,
          problemId: presentation.selectedProblemId,
          resultType: presentation.resultType,
        }
      : null;
    const activeContestantIds = new Set();
    const rows = state.standings.map((standing) => {
      const contestant = contestants.get(normalizedId(standing.contestantId));
      const contestantId = normalizedId(contestant.participationId);
      activeContestantIds.add(contestantId);
      let row = this.rowElements.get(contestantId);
      if (!row) {
        row = this._createContestantRow(contestant);
        this.rowElements.set(contestantId, row);
      }
      this._updateContestantRow(row, contestant, standing, statsByProblem, activeSelection);
      return row;
    });
    for (const [contestantId, row] of this.rowElements) {
      if (!activeContestantIds.has(contestantId)) {
        row.remove();
        this.rowElements.delete(contestantId);
      }
    }
    this._reorderTableBody([...rows, this._updateTotals(stats)]);
    this._renderControls();
  }

  _reorderTableBody(desiredRows) {
    desiredRows.forEach((row, index) => {
      const current = this.nodes.tableBody.children[index] ?? null;
      if (current !== row) {
        this.nodes.tableBody.insertBefore(row, current);
      }
    });
    while (this.nodes.tableBody.children.length > desiredRows.length) {
      this.nodes.tableBody.lastElementChild.remove();
    }
  }

  _createContestantRow(contestant) {
    const row = element("tr", "resolver-row");
    row.dataset.contestantId = contestant.participationId;

    const rank = element("td", "resolver-rank ranking-column");
    const rankValue = element("div");
    rank.append(rankValue);
    rank.dataset.label = this.root.dataset.labelRank || gettext("Rank");
    const contestantCell = element("td", "user-name resolver-contestant");
    contestantCell.dataset.label = this.root.dataset.labelUsername || gettext("Username");
    const layout = element("div", "resolver-contestant__layout");
    const identity = element("div", "usr-ranking-left resolver-contestant__identity");
    const rankDisplayOptions = normalizeRankDisplayOption(
      this.payload.contest.rank_display_options,
    );
    if (rankDisplayOptions === 1 || rankDisplayOptions === 2) {
      contestantCell.classList.add("resolver-contestant--with-visual");
      const visual = element(
        "div",
        `u-logo-ranking resolver-contestant__visual resolver-contestant__visual--${
          rankDisplayOptions === 1 ? "avatar" : "logo"
        }`,
      );
      const visualUrl = rankDisplayOptions === 2 ? contestant.rankLogoUrl : contestant.avatarUrl;
      if (visualUrl) {
        const image = element(
          "img",
          rankDisplayOptions === 1 ? "resolver-contestant__avatar" : "resolver-contestant__logo",
        );
        image.src = visualUrl;
        image.alt = "";
        image.width = 64;
        image.height = 64;
        visual.append(image);
      } else {
        const placeholder = element("div", "resolver-contestant__visual-placeholder");
        placeholder.append(
          element("i", `fa ${rankDisplayOptions === 2 ? "fa-graduation-cap" : "fa-user"}`),
        );
        visual.append(placeholder);
      }
      identity.append(visual, element("div", "u-logo-sep1"));
    }
    const names = element("div", "resolver-contestant__names");
    const handle = contestant.profileUrl
      ? element("a", "resolver-contestant__handle", contestant.displayName || contestant.username)
      : element(
          "strong",
          "resolver-contestant__handle",
          contestant.displayName || contestant.username,
        );
    if (contestant.profileUrl) {
      handle.href = contestant.profileUrl;
    }
    const rating = element("span", contestant.cssClass || "rating rate-none user");
    rating.append(handle);
    names.append(rating);
    if (contestant.fullName) {
      names.append(
        element("div", "personal-info resolver-contestant__display", contestant.fullName),
      );
    }
    identity.append(names);
    const side = element("div", "resolver-contestant__side");
    const organizations = getOrganizationPresentation(contestant.organizations);
    if (organizations.length) {
      const organizationList = element("div", "personal-info resolver-contestant__organization");
      organizations.forEach((organization, index) => {
        if (index) {
          organizationList.append(document.createTextNode(" | "));
        }
        const name = organization.label;
        if (organization.url) {
          const link = element("a", "", name);
          link.href = organization.url;
          organizationList.append(link);
        } else {
          organizationList.append(element("span", "", name));
        }
      });
      side.append(organizationList);
    }
    layout.append(identity, side);
    contestantCell.append(layout);

    const score = element("td", "resolver-metric resolver-metric--score user-points");
    const scoreValue = element("span", "resolver-summary-score");
    score.append(scoreValue);
    let scoreTime = null;
    if (this.payload.contest.format !== "icpc") {
      scoreTime = element("div", "solving-time resolver-summary-time");
      score.append(scoreTime);
    }
    row.append(rank, contestantCell, score);
    let timeCell = null;
    if (this.payload.contest.format === "icpc") {
      timeCell = element("td", "resolver-metric resolver-metric--time user-penalty");
      row.append(timeCell);
    }

    const problemCells = new Map();
    this.problems.forEach((problem) => {
      const problemId = normalizedId(problem.id);
      const tableCell = element("td", "resolver-cell");
      tableCell.dataset.problemId = problem.id;
      tableCell.dataset.label = problem.label;
      problemCells.set(problemId, tableCell);
      row.append(tableCell);
    });
    row._resolverRefs = {
      rankValue,
      contestantCell,
      score,
      scoreValue,
      scoreTime,
      timeCell,
      problemCells,
    };
    return row;
  }

  _updateContestantRow(row, contestant, standing, statsByProblem, activeSelection) {
    const refs = row._resolverRefs;
    row.className = "resolver-row";
    if (contestant.isDisqualified) {
      row.classList.add("resolver-row--disqualified", "disqualified");
    }
    if (
      activeSelection &&
      normalizedId(activeSelection.contestantId) === normalizedId(contestant.participationId)
    ) {
      row.classList.add("resolver-row--target");
      if (activeSelection.resultType) {
        row.classList.add(
          `resolver-row--${activeSelection.resultType.toLowerCase().replaceAll("_", "-")}`,
        );
      }
    }
    refs.rankValue.textContent = String(standing.rank);

    const canRevealContestant =
      this._resolvableForContestant(contestant.participationId).length > 0;
    if (canRevealContestant) {
      refs.contestantCell.dataset.resolverAction = "reveal-contestant";
      refs.contestantCell.dataset.contestantId = contestant.participationId;
      refs.contestantCell.tabIndex = 0;
      refs.contestantCell.setAttribute("role", "button");
      refs.contestantCell.title = gettext("Reveal all results for this contestant");
      refs.contestantCell.setAttribute("aria-label", refs.contestantCell.title);
    } else {
      delete refs.contestantCell.dataset.resolverAction;
      delete refs.contestantCell.dataset.contestantId;
      refs.contestantCell.removeAttribute("tabindex");
      refs.contestantCell.removeAttribute("role");
      refs.contestantCell.removeAttribute("title");
      refs.contestantCell.removeAttribute("aria-label");
    }

    const metric = getMetricPresentation(
      this.payload.contest.format,
      contestant,
      this.payload.contest.points_precision,
    );
    refs.scoreValue.textContent = metric.score;
    refs.score.dataset.label = metric.scoreLabel;
    if (refs.scoreTime) {
      refs.scoreTime.textContent = metric.time;
    }
    if (refs.timeCell) {
      refs.timeCell.textContent = metric.time;
      refs.timeCell.dataset.label = metric.timeLabel;
    }

    this.problems.forEach((problem) => {
      this._updateProblemCell(
        refs.problemCells.get(normalizedId(problem.id)),
        contestant,
        problem,
        statsByProblem.get(normalizedId(problem.id)),
        activeSelection,
      );
    });
  }

  _updateProblemCell(tableCell, contestant, problem, stat, activeSelection) {
    const problemId = normalizedId(problem.id);
    const cell = contestant.problems[problemId];
    const view = getCellPresentation(
      this.payload.contest.format,
      cell,
      this.payload.contest.points_precision,
    );
    const classes = ["resolver-cell", `resolver-cell--${view.state}`];
    const sourceStateClass = {
      solved: "full-score",
      partial: "partial-score",
      failed: "failed-score",
      pending: "pending",
    }[view.state];
    if (sourceStateClass) {
      classes.push(sourceStateClass);
    }
    if (view.state === "pending") {
      if (cell.points === problem.max_score) {
        classes.push("full-score");
      } else if (cell.points !== 0) {
        classes.push("partial-score");
      } else {
        classes.push("failed-score");
      }
    }
    if (
      view.state === "solved" &&
      stat &&
      normalizedId(stat.firstSolveContestantId) === normalizedId(contestant.participationId)
    ) {
      classes.push("resolver-cell--first-solve", "first-solve");
    }
    if (
      activeSelection?.problemId &&
      normalizedId(activeSelection.contestantId) === normalizedId(contestant.participationId) &&
      normalizedId(activeSelection.problemId) === problemId
    ) {
      classes.push("resolver-cell--target");
    }
    tableCell.className = classes.join(" ");

    const signature = JSON.stringify([
      view.state,
      view.resolvable,
      view.primary,
      view.penalty,
      view.pendingCount,
      view.time,
      view.secondary,
      view.accessibleLabel,
    ]);
    if (tableCell._resolverSignature !== signature) {
      const content = view.resolvable
        ? element("button", "resolver-cell__button")
        : element("div", "resolver-cell__result");
      if (view.resolvable) {
        content.type = "button";
        content.dataset.resolverAction = "reveal-cell";
        content.dataset.contestantId = contestant.participationId;
        content.dataset.problemId = problem.id;
        content.setAttribute(
          "aria-label",
          gettext("Reveal %(contestant)s, problem %(problem)s", {
            contestant: contestant.username,
            problem: problem.label,
          }),
        );
      } else {
        content.setAttribute("aria-label", view.accessibleLabel);
      }
      const primaryClass =
        this.payload.contest.format === "icpc" && view.state === "solved"
          ? "resolver-cell__primary solving-time-minute"
          : "resolver-cell__primary";
      content.append(element("span", primaryClass, view.primary));
      if (view.penalty) {
        content.append(element("small", "resolver-cell__penalty", ` (${view.penalty})`));
      }
      if (view.pendingCount) {
        content.append(element("small", "resolver-cell__pending-count", ` [${view.pendingCount}]`));
      }
      if (this.payload.contest.format === "icpc" && view.state === "solved" && view.time) {
        content.append(element("span", "solving-time", view.time));
      }
      if (view.secondary) {
        content.append(
          element(
            "span",
            this.payload.contest.format === "icpc"
              ? "resolver-cell__secondary resolver-cell__tries"
              : "resolver-cell__secondary solving-time",
            view.secondary,
          ),
        );
      }
      tableCell.replaceChildren(content);
      tableCell._resolverSignature = signature;
    }
    const button = tableCell.firstElementChild;
    if (view.resolvable && button instanceof HTMLButtonElement) {
      button.disabled = this.busy;
    }
  }

  _updateTotals(stats) {
    if (!this.totalRow) {
      this.totalRow = element("tr", "resolver-total-row");
      const label = element(
        "td",
        "resolver-total-label",
        this.root.dataset.labelTotalAc || gettext("Total AC"),
      );
      label.colSpan = this.payload.contest.format === "icpc" ? 4 : 3;
      this.totalRow.append(label);
      this.totalRow._resolverTotals = new Map();
      this.problems.forEach((problem) => {
        const total = element("td", "resolver-total total-ac");
        total.dataset.problemId = problem.id;
        this.totalRow._resolverTotals.set(normalizedId(problem.id), total);
        this.totalRow.append(total);
      });
    }
    stats.forEach((stat) => {
      this.totalRow._resolverTotals.get(normalizedId(stat.problemId)).textContent = String(
        stat.totalSolved,
      );
    });
    return this.totalRow;
  }

  _currentProjection() {
    if (!this.planner || this.policyName === "manual") {
      return null;
    }
    const playerState = this.player?.getState();
    if (playerState?.presentation.selectedContestantId && playerState.projection) {
      return playerState.projection;
    }
    const revision = this.session.getRevision();
    if (this.projectionCache?.revision === revision) {
      return this.projectionCache.value;
    }
    const value = this.planner.projectNext(this.session);
    this.projectionCache = { revision, value };
    return value;
  }

  _renderControls() {
    if (!this.session) {
      return;
    }
    const historyCursor = this.session.getHistoryCursor();
    const historyLength = this.session.getHistoryLength();
    const remaining = this.session.getResolvableCount();
    const revealed = this.totalResolvable - remaining;
    const playerState = this.player?.getState() ?? {
      running: false,
      checkpointIndex: 0,
      checkpointCount: 1,
      presentation: {},
    };
    const speed = SPEED_PRESETS[this.speedIndex];
    this.nodes.progress.textContent = gettext("%(revealed)s / %(total)s cells resolved", {
      revealed,
      total: this.totalResolvable,
    });
    this.nodes.status.textContent = remaining
      ? this.statusMessage
      : gettext("Resolver complete — final standings reached.");
    setIconLabel(
      this.nodes.play,
      playerState.running ? "fa-pause" : "fa-play",
      playerState.running ? gettext("Pause") : gettext("Play"),
    );
    this.nodes.play.disabled =
      this.policyName === "manual" ||
      (!remaining && !playerState.projection && !playerState.running);
    this.nodes.play.setAttribute("aria-pressed", String(playerState.running));
    this.nodes.speedLabel.textContent = speed.label;
    this.nodes.slower.disabled = this.speedIndex === 0;
    this.nodes.faster.disabled = this.speedIndex === SPEED_PRESETS.length - 1;
    this.nodes.back.disabled =
      this.busy ||
      playerState.running ||
      (this.policyName === "manual" ? historyCursor === 0 : playerState.checkpointIndex === 0);
    this.nodes.forward.disabled =
      this.busy ||
      playerState.running ||
      (this.policyName === "manual"
        ? historyCursor >= historyLength
        : !remaining && !playerState.projection);
    this.nodes.reset.disabled =
      this.busy ||
      (this.policyName === "manual"
        ? historyCursor === 0
        : playerState.checkpointIndex === 0 && historyCursor === 0);
    this.nodes.replay.disabled = this.busy || this.totalResolvable === 0;
    this.nodes.changeSetup.disabled = this.busy;
    this.nodes.next.disabled =
      this.busy ||
      playerState.running ||
      this.policyName === "manual" ||
      (!remaining && !playerState.projection);
    this.nodes.next.textContent = gettext("Forward");
    this.nodes.forward.textContent =
      this.policyName === "manual" ? gettext("Forward") : gettext("Fast forward");
    this.nodes.toggleHud.setAttribute("aria-pressed", String(this.hudVisible));
    this.nodes.hud.hidden = !this.hudVisible;
    setIconLabel(
      this.nodes.fullscreen,
      document.fullscreenElement ? "fa-compress" : "fa-expand",
      document.fullscreenElement ? gettext("Exit fullscreen") : gettext("Fullscreen"),
    );
    this._updateProblemHeaderAffordances();
    this._renderHud(
      this.hudVisible ? this._currentProjection() : null,
      historyCursor,
      historyLength,
      playerState,
      speed,
    );
  }

  _updateProblemHeaderAffordances() {
    this.problems.forEach((problem) => {
      const button = this.problemHeaderButtons.get(normalizedId(problem.id));
      if (button) {
        button.disabled =
          this.busy || !this.session.getResolvableCellsForProblem(problem.id).length;
      }
    });
  }

  _renderHud(projection, historyCursor, historyLength, playerState, speed) {
    const baseline =
      this.session.baseline === "official-freeze" ? gettext("Freeze") : gettext("Beginning");
    const playback = playerState.running
      ? gettext("playing %(speed)s", { speed: speed.label })
      : gettext("paused %(speed)s", { speed: speed.label });
    this.nodes.hudMode.textContent = `${baseline} · ${
      POLICY_LABELS[this.policyName]
    } · ${playback}`;
    if (projection) {
      const contestant = this.payload.contestants.find(
        (entry) =>
          normalizedId(entry.participation_id) === normalizedId(projection.target.contestantId),
      );
      const problem = this.problems.find(
        (entry) => normalizedId(entry.id) === normalizedId(projection.target.problemId),
      );
      this.nodes.hudTarget.textContent = `${
        contestant?.display_name || contestant?.username || projection.target.contestantId
      } / ${problem?.label ?? projection.target.problemId}`;
      this.nodes.hudCurrentPosition.textContent = gettext("#%(position)s (rank %(rank)s)", {
        position: projection.currentPosition,
        rank: projection.currentRank,
      });
      this.nodes.hudAfterPosition.textContent = gettext("#%(position)s (rank %(rank)s)", {
        position: projection.actualPositionAfterReveal,
        rank: projection.actualRankAfterReveal,
      });
      this.nodes.hudMovement.textContent = projection.movementDelta
        ? `↑ ${projection.movementDelta}`
        : "—";
      this.nodes.hudZone.textContent = projection.entersSingleStepZone
        ? gettext("Enters top %(rank)s", { rank: this.singleStepStartRank })
        : projection.isSingleStep
        ? gettext("Top %(rank)s", { rank: this.singleStepStartRank })
        : gettext("Scoreboard timing");
      this.nodes.hudRemaining.textContent = String(projection.remainingUnresolvedCells);
    } else {
      this.nodes.hudTarget.textContent = "—";
      this.nodes.hudCurrentPosition.textContent = "—";
      this.nodes.hudAfterPosition.textContent = "—";
      this.nodes.hudMovement.textContent = "—";
      this.nodes.hudZone.textContent = "—";
      this.nodes.hudRemaining.textContent = String(this.session.getResolvableCount());
    }
    this.nodes.hudHistory.textContent = gettext(
      "%(cursor)s / %(length)s · pause %(pause)s / %(pauseTotal)s",
      {
        cursor: historyCursor,
        length: historyLength,
        pause: playerState.checkpointIndex,
        pauseTotal: Math.max(0, playerState.checkpointCount - 1),
      },
    );
    this.nodes.hudAward.textContent = this.awardPlaces
      ? gettext("Top %(rank)s timing boundary", { rank: this.awardPlaces })
      : gettext("Off");
    this.nodes.hudSeed.textContent = this.session.seed;
  }

  _resolvableForContestant(contestantId) {
    return this.session.getResolvableCellsForContestant(contestantId);
  }

  _beforePlayerStep(step) {
    if (step.type !== RESOLUTION_STEP_TYPES.REVEAL_CELL) {
      return null;
    }
    this.busy = true;
    return captureRowPositions(this.nodes.tableBody);
  }

  async _performPlayerStep(step, context) {
    if (step.type === RESOLUTION_STEP_TYPES.SCROLL_ROW) {
      const row = [...this.nodes.tableBody.querySelectorAll("tr[data-contestant-id]")].find(
        (candidate) =>
          normalizedId(candidate.dataset.contestantId) === normalizedId(step.target.contestantId),
      );
      row?.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }

    if (step.type === RESOLUTION_STEP_TYPES.SELECT_TEAM) {
      this.statusMessage = gettext("Selected %(contestant)s.", {
        contestant: step.contestantLabel,
      });
    } else if (step.type === RESOLUTION_STEP_TYPES.SELECT_PROBLEM) {
      this.statusMessage = gettext("Selected problem %(problem)s.", {
        problem: step.problemLabel,
      });
    } else if (step.type === RESOLUTION_STEP_TYPES.REVEAL_CELL) {
      const transition = context.transition;
      this.statusMessage = gettext("Revealed %(contestant)s, problem %(problem)s.", {
        contestant: step.contestantLabel,
        problem: step.problemLabel,
      });
      this._render();
      await Promise.all([
        animateRows(this.nodes.tableBody, context.beforeContext, 700),
        animateChangedCells(this.nodes.tableBody, [transition.target]),
      ]);
      this.busy = false;
    } else if (step.type === RESOLUTION_STEP_TYPES.RESULT_MOVE) {
      this.statusMessage = ngettext(
        "%(contestant)s moved up %(count)s position.",
        "%(contestant)s moved up %(count)s positions.",
        step.movementDelta,
        { contestant: step.contestantLabel },
      );
    } else if (step.type === RESOLUTION_STEP_TYPES.RESULT_STAY) {
      this.statusMessage = gettext("%(contestant)s stays in the same position.", {
        contestant: step.contestantLabel,
      });
    } else if (step.type === RESOLUTION_STEP_TYPES.RESULT_FAILED) {
      this.statusMessage = gettext("%(contestant)s received no meaningful score improvement.", {
        contestant: step.contestantLabel,
      });
    } else if (step.type === RESOLUTION_STEP_TYPES.PAUSE) {
      this.statusMessage = gettext("%(reason)s Press Space or Forward to continue.", {
        reason: step.reason,
      });
    }
    this._render();
  }

  async _restorePlayerView() {
    this.busy = false;
    this.statusMessage = this.player?.getState().pauseReason ?? gettext("Resolver state restored.");
    this._render();
  }

  _onPlayerChange(state) {
    if (!this.session) {
      return;
    }
    if (state.running) {
      this.statusMessage = gettext("Playing at %(speed)s.", {
        speed: SPEED_PRESETS[this.speedIndex].label,
      });
    } else if (state.pauseReason) {
      this.statusMessage = state.pauseReason;
    }
    this._render();
  }

  _playToNextPause(includeDelays) {
    if (this.busy || !this.player || this.policyName === "manual") {
      return Promise.resolve(null);
    }
    return this.player.playToNextPause(includeDelays);
  }

  _togglePlayback() {
    if (!this.player || this.policyName === "manual") {
      return;
    }
    if (this.player.getState().running) {
      this.player.cancel();
    } else if (!this.busy) {
      void this.player.playContinuous(true);
    }
  }

  _pausePlayback(reason = gettext("Playback paused.")) {
    if (this.player?.getState().running) {
      this.player.cancel(reason, "operator");
    }
  }

  _changeSpeed(delta) {
    this.speedIndex = clampSpeedIndex(this.speedIndex + delta);
    this.nodes.speed.value = String(this.speedIndex);
    this.player?.setSpeed(SPEED_PRESETS[this.speedIndex].speed);
    this._renderControls();
  }

  async _revealContestant(contestantId, label) {
    const targets = this._resolvableForContestant(contestantId);
    return targets.length ? this._revealTargets(targets, label) : null;
  }

  async _revealProblem(problemId, label) {
    const targets = this.session.getResolvableCellsForProblem(problemId);
    return targets.length ? this._revealTargets(targets, label) : null;
  }

  async _revealTargets(targets, label) {
    if (this.busy || !targets.length) {
      return null;
    }
    this.busy = true;
    const previousPositions = captureRowPositions(this.nodes.tableBody);
    const transition = this.session.revealBatch(targets);
    if (!transition) {
      this.busy = false;
      return null;
    }
    const changedTargets = transition.targets;
    this.statusMessage = ngettext(
      "%(label)s: %(count)s cell.",
      "%(label)s: %(count)s cells.",
      changedTargets.length,
      { label },
    );
    this._render();
    await Promise.all([
      animateRows(this.nodes.tableBody, previousPositions),
      animateChangedCells(this.nodes.tableBody, changedTargets),
    ]);
    this.busy = false;
    if (this.player) {
      await this.player.syncAfterExternalChange(label);
    }
    this._render();
    return { transition };
  }

  async _moveHistory(direction) {
    if (this.busy) {
      return;
    }
    const transition =
      direction === "back" ? this.session.getLastTransition() : this.session.getRedoTransition();
    if (!transition) {
      return;
    }
    this.busy = true;
    const previousPositions = captureRowPositions(this.nodes.tableBody);
    const moved = direction === "back" ? this.session.back() : this.session.forward();
    this.policy.clear();
    if (moved) {
      this.statusMessage =
        direction === "back"
          ? gettext("Stepped back one reveal.")
          : gettext("Stepped forward one reveal.");
      this._render();
      await Promise.all([
        animateRows(this.nodes.tableBody, previousPositions),
        animateChangedCells(this.nodes.tableBody, transition.targets ?? [transition.target]),
      ]);
    }
    this.busy = false;
    this._render();
  }

  async _reset(useReplay) {
    if (this.busy) {
      return;
    }
    this.busy = true;
    const previousPositions = captureRowPositions(this.nodes.tableBody);
    if (this.player && this.policyName !== "manual") {
      await this.player.resetToBeginning();
    } else if (useReplay) {
      this.session.replay();
    } else {
      this.session.reset();
    }
    this.policy.clear();
    this.statusMessage = gettext("%(action)s from %(baseline)s.", {
      action: useReplay ? gettext("Replay") : gettext("Reset"),
      baseline: this._baselineLabel(),
    });
    this._render();
    await animateRows(this.nodes.tableBody, previousPositions);
    this.busy = false;
    this._render();
  }

  async _replay() {
    this._pausePlayback();
    await this._reset(true);
    if (this.player && this.session.getResolvableCount()) {
      void this.player.playContinuous(true);
    }
  }

  _toggleHud() {
    this.hudVisible = !this.hudVisible;
    this._renderControls();
  }

  _showShortcuts() {
    this.helpReturnFocus = document.activeElement;
    this.nodes.shortcuts.hidden = false;
    this.nodes.shortcutsClose.focus();
  }

  _hideShortcuts() {
    if (this.nodes.shortcuts.hidden) {
      return;
    }
    this.nodes.shortcuts.hidden = true;
    if (this.helpReturnFocus instanceof HTMLElement) {
      this.helpReturnFocus.focus();
    }
  }

  async _toggleFullscreen() {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await this.root.requestFullscreen();
      }
    } catch (error) {
      this.statusMessage = gettext("Fullscreen is unavailable: %(error)s", {
        error: error.message,
      });
      this._render();
    }
  }

  _handleShortcut(event) {
    if (isTypingTarget(event.target)) {
      return;
    }
    if (event.key === "Escape") {
      if (!this.nodes.shortcuts.hidden) {
        event.preventDefault();
        this._hideShortcuts();
      }
      return;
    }
    if (this.nodes.workspace.hidden || !this.session) {
      return;
    }
    const key = event.key.toLowerCase();
    if (key === "?" || key === "/") {
      event.preventDefault();
      this._showShortcuts();
      return;
    }
    if (event.repeat && !["[", "]", "arrowleft", "arrowright"].includes(key)) {
      return;
    }
    if (key === "p") {
      event.preventDefault();
      this._togglePlayback();
    } else if (key === " ") {
      event.preventDefault();
      if (this.player?.getState().running) {
        this.player.cancel();
      } else {
        void this._playToNextPause(true);
      }
    } else if (key === "[") {
      event.preventDefault();
      this._changeSpeed(-1);
    } else if (key === "]") {
      event.preventDefault();
      this._changeSpeed(1);
    } else if (/^[1-4]$/.test(key)) {
      event.preventDefault();
      this.speedIndex = Number(key) - 1;
      this.nodes.speed.value = String(this.speedIndex);
      this.player?.setSpeed(SPEED_PRESETS[this.speedIndex].speed);
      this._renderControls();
    } else if (key === "h") {
      event.preventDefault();
      this._toggleHud();
    } else if (key === "f") {
      event.preventDefault();
      void this._toggleFullscreen();
    } else if (key === "backspace" || key === "arrowleft") {
      event.preventDefault();
      this._pausePlayback();
      if (this.policyName === "manual") {
        void this._moveHistory("back");
      } else {
        void this.player?.rewindToPreviousPause();
      }
    } else if (key === "arrowright") {
      event.preventDefault();
      if (this.policyName === "manual") {
        void this._moveHistory("forward");
      } else {
        void this._playToNextPause(true);
      }
    } else if (key === ".") {
      event.preventDefault();
      void this._playToNextPause(false);
    }
  }
}
