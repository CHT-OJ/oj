import { animateChangedCells, animateRows, captureRowPositions } from "./animation.js";
import {
  AutoplayController,
  CEREMONY_PRESETS,
  getPauseReason,
  normalizeAwardPlaces,
} from "./controller.js";
import { ResolverSession } from "./core.js";
import { BottomUpStickyPolicy, ByContestantPolicy, ByProblemPolicy } from "./policies.js";
import { deriveProblemStats, getCellPresentation, getMetricPresentation } from "./presentation.js";

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
    this.policy = new BottomUpStickyPolicy();
    this.policyName = "bottom-up-sticky";
    this.granularity = "cell";
    this.pauseBeats = { ...CEREMONY_PRESETS.icpc.pauseBeats };
    this.awardPlaces = Math.min(3, payload.contestants.length);
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
      pauseRank: root.querySelector('[name="pause_rank"]'),
      pauseAward: root.querySelector('[name="pause_award"]'),
      pauseFinished: root.querySelector('[name="pause_finished"]'),
      pauseFirstSolve: root.querySelector('[name="pause_first_solve"]'),
      freezeNote: root.querySelector("#resolver-freeze-note"),
      workspace: root.querySelector("#resolver-workspace"),
      table: root.querySelector("#ranking-table"),
      tableHead: root.querySelector("#resolver-table-head"),
      tableBody: root.querySelector("#resolver-table-body"),
      tableFoot: root.querySelector("#resolver-table-foot"),
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
      hudSeed: root.querySelector("#resolver-hud-seed"),
      shortcuts: root.querySelector("#resolver-shortcuts"),
      shortcutsClose: root.querySelector("#resolver-shortcuts-close"),
    };
    this.autoplay = new AutoplayController({
      step: () => this._autoplayStep(),
      onChange: (state) => this._onAutoplayChange(state),
      speedIndex: 1,
    });
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
    this.nodes.next.addEventListener("click", () => this._stepFromOperator("Next control"));
    this.nodes.play.addEventListener("click", () => this._toggleAutoplay());
    this.nodes.slower.addEventListener("click", () => this.autoplay.slower());
    this.nodes.faster.addEventListener("click", () => this.autoplay.faster());
    this.nodes.back.addEventListener("click", () => {
      this._pauseAutoplay();
      void this._moveHistory("back");
    });
    this.nodes.forward.addEventListener("click", () => {
      this._pauseAutoplay();
      void this._moveHistory("forward");
    });
    this.nodes.reset.addEventListener("click", () => {
      this._pauseAutoplay();
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
      const button = event.target.closest("button[data-resolver-action]");
      if (!button || this.busy) {
        return;
      }
      this._pauseAutoplay("Autoplay paused for a manual reveal.");
      this.policy.clear();
      if (button.dataset.resolverAction === "reveal-cell") {
        void this._revealTargets(
          [
            {
              contestantId: button.dataset.contestantId,
              problemId: button.dataset.problemId,
            },
          ],
          "Manual cell reveal",
        );
      } else if (button.dataset.resolverAction === "reveal-contestant") {
        void this._revealContestant(button.dataset.contestantId, "Manual contestant reveal");
      }
    });
    document.addEventListener("keydown", (event) => this._handleShortcut(event));
    document.addEventListener("fullscreenchange", () => this._renderControls(this._selectTarget()));
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
    this.nodes.pauseRank.checked = preset.pauseBeats.rankChange;
    this.nodes.pauseAward.checked = preset.pauseBeats.awardZone;
    this.nodes.pauseFinished.checked = preset.pauseBeats.contestantFinished;
    this.nodes.pauseFirstSolve.checked = preset.pauseBeats.firstSolve;
    this.autoplay.setSpeed(preset.speedIndex);
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
    this._pauseAutoplay();
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
    this.pauseBeats = {
      rankChange: this.nodes.pauseRank.checked,
      awardZone: this.nodes.pauseAward.checked,
      contestantFinished: this.nodes.pauseFinished.checked,
      firstSolve: this.nodes.pauseFirstSolve.checked,
    };
    this.autoplay.setSpeed(Number(this.nodes.speed.value));
    this.totalResolvable = this.session.getResolvableCells().length;
    this.statusMessage = `Started from ${this._baselineLabel()}.`;
    this.nodes.setup.hidden = true;
    this.nodes.workspace.hidden = false;
    window.CHTOJResolverSession = this.session;
    this._renderTableHead();
    this._render();
  }

  _createPolicy(name) {
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
    this._pauseAutoplay();
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
    const nextTarget = this._selectTarget();
    const rows = state.standings.map((standing) => {
      const contestant = contestants.get(normalizedId(standing.contestantId));
      return this._renderContestantRow(contestant, standing, statsByProblem, nextTarget);
    });
    this.nodes.tableBody.replaceChildren(...rows);
    this._renderTotals(stats);
    this._renderControls(nextTarget);
  }

  _renderContestantRow(contestant, standing, statsByProblem, nextTarget) {
    const row = element("tr", "resolver-row");
    row.dataset.contestantId = contestant.participationId;
    if (contestant.isDisqualified) {
      row.classList.add("resolver-row--disqualified", "disqualified");
    } else if (this.awardPlaces > 0 && standing.rank <= this.awardPlaces) {
      row.classList.add("resolver-row--award");
      if (standing.rank === 1) {
        row.classList.add("resolver-row--award-first");
      }
    }
    if (
      nextTarget &&
      normalizedId(nextTarget.contestantId) === normalizedId(contestant.participationId)
    ) {
      row.classList.add("resolver-row--target");
    }

    const rank = element("td", "resolver-rank ranking-column");
    rank.append(element("div", "", String(standing.rank)));
    rank.dataset.label = "Rank";
    const contestantCell = element("td", "user-name resolver-contestant");
    contestantCell.dataset.label = "Contestant";
    const layout = element("div", "resolver-contestant__layout");
    const identity = element("div", "usr-ranking-left resolver-contestant__identity");
    const rankDisplayOptions = Number(this.payload.contest.rank_display_options ?? 1);
    if (rankDisplayOptions !== 3) {
      const visual = element("div", "u-logo-ranking");
      const visualUrl = rankDisplayOptions === 2 ? contestant.rankLogoUrl : contestant.avatarUrl;
      if (visualUrl) {
        const avatar = element("img", "resolver-contestant__avatar");
        avatar.src = visualUrl;
        avatar.alt = "";
        avatar.width = 64;
        avatar.height = 64;
        visual.append(avatar);
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
      ? element("a", "resolver-contestant__handle", contestant.username)
      : element("strong", "resolver-contestant__handle", contestant.username);
    if (contestant.profileUrl) {
      handle.href = contestant.profileUrl;
    }
    const rating = element("span", contestant.cssClass || "rating rate-none user");
    rating.append(handle);
    names.append(rating);
    if (contestant.displayName && contestant.displayName !== contestant.username) {
      names.append(
        element("div", "personal-info resolver-contestant__display", contestant.displayName),
      );
    }
    const organization = contestant.organization?.short_name || contestant.organization?.name;
    identity.append(names);
    const side = element("div", "resolver-contestant__side");
    const revealContestant = element("button", "resolver-row-reveal");
    revealContestant.type = "button";
    revealContestant.dataset.resolverAction = "reveal-contestant";
    revealContestant.dataset.contestantId = contestant.participationId;
    revealContestant.setAttribute("aria-label", `Reveal ${contestant.username}`);
    revealContestant.title = "Reveal contestant";
    revealContestant.append(element("i", "fa fa-play fa-fw"));
    revealContestant.disabled =
      this.busy || !this._resolvableForContestant(contestant.participationId).length;
    side.append(revealContestant);
    if (organization) {
      side.append(element("div", "personal-info resolver-contestant__organization", organization));
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
        nextTarget &&
        normalizedId(nextTarget.contestantId) === normalizedId(contestant.participationId) &&
        normalizedId(nextTarget.problemId) === problemId
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
      content.append(element("span", "resolver-cell__primary", view.primary));
      if (view.secondary) {
        content.append(element("span", "resolver-cell__secondary", view.secondary));
      }
      tableCell.append(content);
      row.append(tableCell);
    });
    return row;
  }

  _renderTotals(stats) {
    const row = element("tr", "resolver-total-row");
    const label = element("td", "resolver-total-label", "Total AC");
    label.colSpan = this.payload.contest.format === "icpc" ? 4 : 3;
    row.append(label);
    stats.forEach((stat) => {
      const total = element("td", "resolver-total total-ac", String(stat.totalSolved));
      total.dataset.problemId = stat.problemId;
      row.append(total);
    });
    this.nodes.tableFoot.replaceChildren(row);
  }

  _renderControls(nextTarget) {
    if (!this.session) {
      return;
    }
    const history = this.session.getHistory();
    const remaining = this.session.getResolvableCells().length;
    const revealed = this.totalResolvable - remaining;
    const autoplay = this.autoplay.getState();
    this.nodes.progress.textContent = `${revealed} / ${this.totalResolvable} cells resolved`;
    this.nodes.status.textContent = remaining
      ? this.statusMessage
      : "Resolver complete — final standings reached.";
    this.nodes.play.innerHTML = autoplay.playing
      ? '<i class="fa fa-pause"></i> Pause'
      : '<i class="fa fa-play"></i> Play';
    this.nodes.play.disabled = this.policyName === "manual" || (!nextTarget && !autoplay.playing);
    this.nodes.play.setAttribute("aria-pressed", String(autoplay.playing));
    this.nodes.speedLabel.textContent = autoplay.speed.label;
    this.nodes.slower.disabled = autoplay.speedIndex === 0;
    this.nodes.faster.disabled = autoplay.speedIndex === 3;
    this.nodes.back.disabled = this.busy || history.cursor === 0;
    this.nodes.forward.disabled = this.busy || history.cursor >= history.transitions.length;
    this.nodes.reset.disabled = this.busy || history.cursor === 0;
    this.nodes.replay.disabled = this.busy || this.totalResolvable === 0;
    this.nodes.changeSetup.disabled = this.busy;
    this.nodes.next.disabled =
      this.busy || autoplay.playing || this.policyName === "manual" || !nextTarget;
    this.nodes.next.textContent =
      this.granularity === "contestant" ? "Reveal next contestant" : "Reveal next cell";
    this.nodes.toggleHud.setAttribute("aria-pressed", String(this.hudVisible));
    this.nodes.hud.hidden = !this.hudVisible;
    this.nodes.fullscreen.innerHTML = document.fullscreenElement
      ? '<i class="fa fa-compress"></i> Exit fullscreen'
      : '<i class="fa fa-expand"></i> Fullscreen';
    this._renderHud(nextTarget, history, autoplay);
  }

  _renderHud(nextTarget, history, autoplay) {
    const baseline = this.session.baseline === "official-freeze" ? "Freeze" : "Beginning";
    const playback = autoplay.playing
      ? `playing ${autoplay.speed.label}`
      : `paused ${autoplay.speed.label}`;
    this.nodes.hudMode.textContent = `${baseline} · ${
      POLICY_LABELS[this.policyName]
    } · ${playback}`;
    if (nextTarget) {
      const contestant = this.payload.contestants.find(
        (entry) => normalizedId(entry.participation_id) === normalizedId(nextTarget.contestantId),
      );
      const problem = this.problems.find(
        (entry) => normalizedId(entry.id) === normalizedId(nextTarget.problemId),
      );
      this.nodes.hudTarget.textContent = `${contestant?.username ?? nextTarget.contestantId} / ${
        problem?.label ?? nextTarget.problemId
      }`;
    } else {
      this.nodes.hudTarget.textContent = "—";
    }
    this.nodes.hudHistory.textContent = `${history.cursor} / ${history.transitions.length}`;
    this.nodes.hudAward.textContent = this.awardPlaces ? `Top ${this.awardPlaces}` : "Off";
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

  async _stepFromOperator(label) {
    this._pauseAutoplay();
    await this._revealNext(label);
  }

  async _revealNext(label = "Reveal") {
    if (this.busy || this.policyName === "manual") {
      return null;
    }
    const target = this.policy.select(this.session);
    if (!target) {
      return null;
    }
    if (this.granularity === "contestant") {
      return this._revealContestant(target.contestantId, `${label}, contestant`);
    }
    return this._revealTargets([target], `${label}, cell`);
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
    this._render();
    return { transitions };
  }

  async _autoplayStep() {
    const result = await this._revealNext("Autoplay");
    if (!result) {
      return { complete: true, pauseReason: null };
    }
    const complete = this.session.getResolvableCells().length === 0;
    return {
      complete,
      pauseReason: complete
        ? null
        : getPauseReason(result.transitions, this.pauseBeats, this.awardPlaces),
    };
  }

  _toggleAutoplay() {
    if (this.policyName === "manual") {
      return;
    }
    if (this.autoplay.playing) {
      this.autoplay.pause();
      return;
    }
    if (this.busy) {
      return;
    }
    this.autoplay.toggle();
  }

  _pauseAutoplay(reason = "Autoplay paused.") {
    if (this.autoplay.playing) {
      this.autoplay.pause(reason, "operator");
    }
  }

  _onAutoplayChange(state) {
    if (!this.session) {
      return;
    }
    if (state.playing) {
      this.statusMessage = `Autoplay running at ${state.speed.label}.`;
    } else if (state.pauseKind === "beat") {
      this.statusMessage = `Paused on ceremony beat — ${state.pauseReason} Press Space to resume.`;
    } else if (state.pauseKind === "complete") {
      this.statusMessage = state.pauseReason;
    } else if (state.pauseReason) {
      this.statusMessage = state.pauseReason;
    }
    this._render();
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
    if (useReplay) {
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
    this._pauseAutoplay();
    await this._reset(true);
    if (this.policyName !== "manual" && this.session.getResolvableCells().length) {
      this.autoplay.play();
    }
  }

  _toggleHud() {
    this.hudVisible = !this.hudVisible;
    this._renderControls(this._selectTarget());
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
      this._toggleAutoplay();
    } else if (key === " ") {
      event.preventDefault();
      if (this.autoplay.playing) {
        this.autoplay.pause();
      } else if (this.autoplay.pauseKind === "beat") {
        this.autoplay.play();
      } else {
        void this._stepFromOperator("Keyboard step");
      }
    } else if (key === "[") {
      event.preventDefault();
      this.autoplay.slower();
    } else if (key === "]") {
      event.preventDefault();
      this.autoplay.faster();
    } else if (/^[1-4]$/.test(key)) {
      event.preventDefault();
      this.autoplay.setSpeed(Number(key) - 1);
    } else if (key === "h") {
      event.preventDefault();
      this._toggleHud();
    } else if (key === "f") {
      event.preventDefault();
      void this._toggleFullscreen();
    } else if (key === "backspace" || key === "arrowleft") {
      event.preventDefault();
      this._pauseAutoplay();
      void this._moveHistory("back");
    } else if (key === "arrowright") {
      event.preventDefault();
      this._pauseAutoplay();
      const history = this.session.getHistory();
      if (history.cursor < history.transitions.length) {
        void this._moveHistory("forward");
      } else {
        void this._revealNext("Keyboard next");
      }
    }
  }
}
