import { animateChangedCells, animateRows, captureRowPositions } from "./animation.js";
import {
  CEREMONY_PRESETS,
  SPEED_PRESETS,
  clampSpeedIndex,
  normalizeAwardPlaces,
  normalizeSingleStepStartRank,
} from "./controller.js";
import { ResolverSession } from "./core.js";
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

const POLICY_LABELS = Object.freeze({
  "row-sweep": "ICPC row sweep",
  "bottom-up-sticky": "Bottom-up",
  "by-problem": "By problem",
  "by-contestant": "By contestant",
  manual: "Manual",
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
    this.granularity = "cell";
    this.hardPauses = { ...CEREMONY_PRESETS.icpc.hardPauses };
    this.awardPlaces = Math.min(6, payload.contestants.length);
    this.singleStepStartRank = Math.min(6, payload.contestants.length);
    this.speedIndex = 1;
    this.planner = null;
    this.player = null;
    this.busy = false;
    this.totalResolvable = 0;
    this.hudVisible = true;
    this.activePreset = "icpc";
    this.statusMessage = "Choose a ceremony preset to begin.";
    this.helpReturnFocus = null;

    this.nodes = {
      setup: root.querySelector("#resolver-setup"),
      setupForm: root.querySelector("#resolver-setup-form"),
      presetButtons: [...root.querySelectorAll("[data-resolver-preset]")],
      baseline: root.querySelector("#resolver-baseline"),
      policy: root.querySelector("#resolver-policy"),
      granularity: root.querySelector("#resolver-granularity"),
      tieOrder: root.querySelector("#resolver-tie-order"),
      speed: root.querySelector("#resolver-speed"),
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
    autoOption.textContent = freezeAvailable ? "Auto (official freeze)" : "Auto (beginning)";
    freezeOption.disabled = !freezeAvailable;
    this.nodes.awardPlaces.max = String(this.payload.contestants.length);
    this.nodes.awardPlaces.value = String(this.awardPlaces);
    this.nodes.singleStepStartRank.max = String(this.payload.contestants.length);
    this.nodes.singleStepStartRank.value = String(this.singleStepStartRank);
    this.nodes.freezeNote.textContent = freezeAvailable
      ? `Official freeze is available (${this.payload.contest.frozen_last_minutes} minutes).`
      : "This format has no native official-freeze state; Auto uses Beginning.";
  }

  _bindEvents() {
    this.nodes.setupForm.addEventListener("submit", (event) => {
      event.preventDefault();
      this._start();
    });
    this.nodes.presetButtons.forEach((button) => {
      button.addEventListener("click", () => this._applyPreset(button.dataset.resolverPreset));
    });
    this.nodes.setupForm.addEventListener("change", (event) => {
      if (!event.target.closest("[data-resolver-preset]")) {
        this.activePreset = "custom";
        this._renderPresetSelection();
      }
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
      this._pausePlayback("Playback paused for a manual reveal.");
      this.policy.clear();
      if (action.dataset.resolverAction === "reveal-cell") {
        void this._revealTargets(
          [
            {
              contestantId: action.dataset.contestantId,
              problemId: action.dataset.problemId,
            },
          ],
          "Manual cell reveal",
        );
      } else if (action.dataset.resolverAction === "reveal-contestant") {
        void this._revealContestant(action.dataset.contestantId, "Manual contestant reveal");
      }
    });
    this.nodes.tableBody.addEventListener("keydown", (event) => {
      const action = event.target.closest('[data-resolver-action="reveal-contestant"]');
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
    this.activePreset = name;
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
    this._renderPresetSelection();
  }

  _renderPresetSelection() {
    this.nodes.presetButtons.forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.resolverPreset === this.activePreset),
      );
    });
  }

  _start() {
    this._pausePlayback();
    try {
      this.session = new ResolverSession(this.payload, {
        baseline: this.nodes.baseline.value,
        tieOrder: this.nodes.tieOrder.value,
      });
    } catch (error) {
      this.nodes.freezeNote.textContent = `Resolver could not start: ${error.message}`;
      return;
    }

    this.policyName = this.nodes.policy.value;
    this.granularity = this.nodes.granularity.value;
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
      singleStep: true,
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
    this.totalResolvable = this.session.getResolvableCells().length;
    this.statusMessage = `Started from ${this._baselineLabel()}.`;
    this.nodes.setup.hidden = true;
    this.nodes.workspace.hidden = false;
    window.CHTOJResolverSession = this.session;
    this._renderTableHead();
    this._render();
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
    return this.session.baseline === "official-freeze" ? "official freeze" : "the beginning";
  }

  _renderTableHead() {
    const formatName = this.payload.contest.format;
    const metrics = getMetricPresentation(formatName, { score: 0, cumtime: 0 });
    const labels = this.root.dataset;
    const row = element("tr");
    const coreHeaders = [
      { label: labels.labelRank || "Rank", className: "header rank" },
      { label: labels.labelUsername || "Username", className: "header username" },
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
    this.problems.forEach((problem) => {
      const header = element("th", "resolver-heading resolver-heading--problem header points");
      header.scope = "col";
      header.title = `${problem.code} — ${problem.name}`;
      header.append(element("span", "resolver-problem-label", problem.label));
      if (formatName !== "icpc") {
        header.append(
          element(
            "span",
            "resolver-problem-denominator point-denominator",
            String(problem.max_score),
          ),
        );
      }
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
    const rows = state.standings.map((standing) => {
      const contestant = contestants.get(normalizedId(standing.contestantId));
      return this._renderContestantRow(contestant, standing, statsByProblem, activeSelection);
    });
    this.nodes.tableBody.replaceChildren(...rows, this._renderTotals(stats));
    this._renderControls();
  }

  _renderContestantRow(contestant, standing, statsByProblem, activeSelection) {
    const row = element("tr", "resolver-row");
    row.dataset.contestantId = contestant.participationId;
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

    const rank = element("td", "resolver-rank ranking-column");
    rank.append(element("div", "", String(standing.rank)));
    rank.dataset.label = "Rank";
    const contestantCell = element("td", "user-name resolver-contestant");
    contestantCell.dataset.label = "Contestant";
    const layout = element("div", "resolver-contestant__layout");
    const identity = element("div", "usr-ranking-left resolver-contestant__identity");
    const rankDisplayOptions = normalizeRankDisplayOption(
      this.payload.contest.rank_display_options,
    );
    if (rankDisplayOptions === 1 || rankDisplayOptions === 2) {
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
    if (this._resolvableForContestant(contestant.participationId).length) {
      contestantCell.dataset.resolverAction = "reveal-contestant";
      contestantCell.dataset.contestantId = contestant.participationId;
      contestantCell.tabIndex = 0;
      contestantCell.title = `Reveal ${contestant.username}`;
    }
    layout.append(identity, side);
    contestantCell.append(layout);

    const metric = getMetricPresentation(
      this.payload.contest.format,
      contestant,
      this.payload.contest.points_precision,
    );
    const score = element("td", "resolver-metric resolver-metric--score user-points");
    score.append(element("span", "resolver-summary-score", metric.score));
    if (this.payload.contest.format !== "icpc") {
      score.append(element("div", "solving-time resolver-summary-time", metric.time));
    }
    score.dataset.label = metric.scoreLabel;
    row.append(rank, contestantCell, score);
    if (this.payload.contest.format === "icpc") {
      const time = element("td", "resolver-metric resolver-metric--time user-penalty", metric.time);
      time.dataset.label = metric.timeLabel;
      row.append(time);
    }

    this.problems.forEach((problem) => {
      const problemId = normalizedId(problem.id);
      const cell = contestant.problems[problemId];
      const view = getCellPresentation(
        this.payload.contest.format,
        cell,
        this.payload.contest.points_precision,
      );
      const tableCell = element("td", `resolver-cell resolver-cell--${view.state}`);
      const sourceStateClass = {
        solved: "full-score",
        partial: "partial-score",
        failed: "failed-score",
        pending: "pending",
      }[view.state];
      if (sourceStateClass) {
        tableCell.classList.add(sourceStateClass);
      }
      if (view.state === "pending") {
        if (cell.points === problem.max_score) {
          tableCell.classList.add("full-score");
        } else if (cell.points !== 0) {
          tableCell.classList.add("partial-score");
        } else {
          tableCell.classList.add("failed-score");
        }
      }
      tableCell.dataset.problemId = problem.id;
      tableCell.dataset.label = problem.label;
      const stat = statsByProblem.get(problemId);
      if (
        view.state === "solved" &&
        stat &&
        normalizedId(stat.firstSolveContestantId) === normalizedId(contestant.participationId)
      ) {
        tableCell.classList.add("resolver-cell--first-solve", "first-solve");
      }
      if (
        activeSelection?.problemId &&
        normalizedId(activeSelection.contestantId) === normalizedId(contestant.participationId) &&
        normalizedId(activeSelection.problemId) === problemId
      ) {
        tableCell.classList.add("resolver-cell--target");
      }

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
          `Reveal ${contestant.username}, problem ${problem.label}`,
        );
        content.disabled = this.busy;
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
      tableCell.append(content);
      row.append(tableCell);
    });
    return row;
  }

  _renderTotals(stats) {
    const row = element("tr", "resolver-total-row");
    const label = element(
      "td",
      "resolver-total-label",
      this.root.dataset.labelTotalAc || "Total AC",
    );
    label.colSpan = this.payload.contest.format === "icpc" ? 4 : 3;
    row.append(label);
    stats.forEach((stat) => {
      const total = element("td", "resolver-total total-ac", String(stat.totalSolved));
      total.dataset.problemId = stat.problemId;
      row.append(total);
    });
    return row;
  }

  _currentProjection() {
    if (!this.planner || this.policyName === "manual") {
      return null;
    }
    const playerState = this.player?.getState();
    if (playerState?.presentation.selectedContestantId && playerState.projection) {
      return playerState.projection;
    }
    return this.planner.projectNext(this.session);
  }

  _renderControls() {
    if (!this.session) {
      return;
    }
    const history = this.session.getHistory();
    const remaining = this.session.getResolvableCells().length;
    const revealed = this.totalResolvable - remaining;
    const nextTarget = this._selectTarget();
    const playerState = this.player?.getState() ?? {
      running: false,
      checkpointIndex: 0,
      checkpointCount: 1,
      presentation: {},
    };
    const speed = SPEED_PRESETS[this.speedIndex];
    this.nodes.progress.textContent = `${revealed} / ${this.totalResolvable} cells resolved`;
    this.nodes.status.textContent = remaining
      ? this.statusMessage
      : "Resolver complete — final standings reached.";
    this.nodes.play.innerHTML = playerState.running
      ? '<i class="fa fa-pause"></i> Pause'
      : '<i class="fa fa-play"></i> Play';
    this.nodes.play.disabled =
      this.policyName === "manual" ||
      (!nextTarget && !playerState.projection && !playerState.running);
    this.nodes.play.setAttribute("aria-pressed", String(playerState.running));
    this.nodes.speedLabel.textContent = speed.label;
    this.nodes.slower.disabled = this.speedIndex === 0;
    this.nodes.faster.disabled = this.speedIndex === SPEED_PRESETS.length - 1;
    this.nodes.back.disabled =
      this.busy ||
      playerState.running ||
      (this.policyName === "manual" ? history.cursor === 0 : playerState.checkpointIndex === 0);
    this.nodes.forward.disabled =
      this.busy ||
      playerState.running ||
      (this.policyName === "manual"
        ? history.cursor >= history.transitions.length
        : !nextTarget && !playerState.projection);
    this.nodes.reset.disabled =
      this.busy ||
      (this.policyName === "manual"
        ? history.cursor === 0
        : playerState.checkpointIndex === 0 && history.cursor === 0);
    this.nodes.replay.disabled = this.busy || this.totalResolvable === 0;
    this.nodes.changeSetup.disabled = this.busy;
    this.nodes.next.disabled =
      this.busy ||
      playerState.running ||
      this.policyName === "manual" ||
      (!nextTarget && !playerState.projection);
    this.nodes.next.textContent = "Forward";
    this.nodes.forward.textContent = this.policyName === "manual" ? "Forward" : "Fast forward";
    this.nodes.toggleHud.setAttribute("aria-pressed", String(this.hudVisible));
    this.nodes.hud.hidden = !this.hudVisible;
    this.nodes.fullscreen.innerHTML = document.fullscreenElement
      ? '<i class="fa fa-compress"></i> Exit fullscreen'
      : '<i class="fa fa-expand"></i> Fullscreen';
    this._renderHud(this._currentProjection(), history, playerState, speed);
  }

  _renderHud(projection, history, playerState, speed) {
    const baseline = this.session.baseline === "official-freeze" ? "Freeze" : "Beginning";
    const playback = playerState.running ? `playing ${speed.label}` : `paused ${speed.label}`;
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
      this.nodes.hudCurrentPosition.textContent = `#${projection.currentPosition} (rank ${projection.currentRank})`;
      this.nodes.hudAfterPosition.textContent = `#${projection.actualPositionAfterReveal} (rank ${projection.actualRankAfterReveal})`;
      this.nodes.hudMovement.textContent = projection.movementDelta
        ? `↑ ${projection.movementDelta}`
        : "—";
      this.nodes.hudZone.textContent = projection.entersSingleStepZone
        ? `Enters top ${this.singleStepStartRank}`
        : projection.isSingleStep
        ? `Top ${this.singleStepStartRank}`
        : "Scoreboard timing";
      this.nodes.hudRemaining.textContent = String(projection.remainingUnresolvedCells);
    } else {
      this.nodes.hudTarget.textContent = "—";
      this.nodes.hudCurrentPosition.textContent = "—";
      this.nodes.hudAfterPosition.textContent = "—";
      this.nodes.hudMovement.textContent = "—";
      this.nodes.hudZone.textContent = "—";
      this.nodes.hudRemaining.textContent = String(this.session.getResolvableCells().length);
    }
    this.nodes.hudHistory.textContent = `${history.cursor} / ${
      history.transitions.length
    } · pause ${playerState.checkpointIndex} / ${Math.max(0, playerState.checkpointCount - 1)}`;
    this.nodes.hudAward.textContent = this.awardPlaces
      ? `Top ${this.awardPlaces} timing boundary`
      : "Off";
    this.nodes.hudSeed.textContent = this.session.seed;
  }

  _selectTarget() {
    return this.session && this.policyName !== "manual" ? this.policy.select(this.session) : null;
  }

  _resolvableForContestant(contestantId) {
    return this.session
      .getResolvableCells()
      .filter((cell) => normalizedId(cell.contestantId) === normalizedId(contestantId));
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
      this.statusMessage = `Selected ${step.contestantLabel}.`;
    } else if (step.type === RESOLUTION_STEP_TYPES.SELECT_PROBLEM) {
      this.statusMessage = `Selected problem ${step.problemLabel}.`;
    } else if (step.type === RESOLUTION_STEP_TYPES.REVEAL_CELL) {
      const transition = context.transition;
      this.statusMessage = `Revealed ${step.contestantLabel}, problem ${step.problemLabel}.`;
      this._render();
      await Promise.all([
        animateRows(this.nodes.tableBody, context.beforeContext, 700),
        animateChangedCells(this.nodes.tableBody, [transition.target]),
      ]);
      this.busy = false;
    } else if (step.type === RESOLUTION_STEP_TYPES.RESULT_MOVE) {
      this.statusMessage = `${step.contestantLabel} moved up ${step.movementDelta} position${
        step.movementDelta === 1 ? "" : "s"
      }.`;
    } else if (step.type === RESOLUTION_STEP_TYPES.RESULT_STAY) {
      this.statusMessage = `${step.contestantLabel} stays in the same position.`;
    } else if (step.type === RESOLUTION_STEP_TYPES.RESULT_FAILED) {
      this.statusMessage = `${step.contestantLabel} received no meaningful score improvement.`;
    } else if (step.type === RESOLUTION_STEP_TYPES.PAUSE) {
      this.statusMessage = `${step.reason} Press Space or Forward to continue.`;
    }
    this._render();
  }

  async _restorePlayerView() {
    this.busy = false;
    this.statusMessage = this.player?.getState().pauseReason ?? "Resolver state restored.";
    this._render();
  }

  _onPlayerChange(state) {
    if (!this.session) {
      return;
    }
    if (state.running) {
      this.statusMessage = `Playing at ${SPEED_PRESETS[this.speedIndex].label}.`;
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
      void this.player.playToNextPause(true);
    }
  }

  _pausePlayback(reason = "Playback paused.") {
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

  async _revealTargets(targets, label) {
    if (this.busy || !targets.length) {
      return null;
    }
    this.busy = true;
    const previousPositions = captureRowPositions(this.nodes.tableBody);
    const transitions = [];
    targets.forEach((target) => {
      const transition = this.session.revealCell(target.contestantId, target.problemId);
      if (transition) {
        transitions.push(transition);
      }
    });
    this.statusMessage = `${label}: ${transitions.length} ${
      transitions.length === 1 ? "cell" : "cells"
    }.`;
    this._render();
    await Promise.all([
      animateRows(this.nodes.tableBody, previousPositions),
      animateChangedCells(
        this.nodes.tableBody,
        transitions.map((transition) => transition.target),
      ),
    ]);
    this.busy = false;
    if (this.player) {
      await this.player.syncAfterExternalChange(label);
    }
    this._render();
    return { transitions };
  }

  async _moveHistory(direction) {
    if (this.busy) {
      return;
    }
    const history = this.session.getHistory();
    const transition =
      direction === "back"
        ? history.transitions[history.cursor - 1]
        : history.transitions[history.cursor];
    if (!transition) {
      return;
    }
    this.busy = true;
    const previousPositions = captureRowPositions(this.nodes.tableBody);
    const moved = direction === "back" ? this.session.back() : this.session.forward();
    this.policy.clear();
    if (moved) {
      this.statusMessage =
        direction === "back" ? "Stepped back one reveal." : "Stepped forward one reveal.";
      this._render();
      await Promise.all([
        animateRows(this.nodes.tableBody, previousPositions),
        animateChangedCells(this.nodes.tableBody, [transition.target]),
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
    this.statusMessage = `${useReplay ? "Replay" : "Reset"} from ${this._baselineLabel()}.`;
    this._render();
    await animateRows(this.nodes.tableBody, previousPositions);
    this.busy = false;
    this._render();
  }

  async _replay() {
    this._pausePlayback();
    await this._reset(true);
    if (this.player && this.session.getResolvableCells().length) {
      void this.player.playToNextPause(true);
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
      this.statusMessage = `Fullscreen is unavailable: ${error.message}`;
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
