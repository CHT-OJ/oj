/* Score cells, first solves and Total AC from VNOI-Admin/OJ #626 (7900e2f80).
 * CHTOJ keeps its server-rendered standings header, profile cells and admin forms.
 */
(function ($) {
    'use strict';

    // ─── Utilities ───────────────────────────────────────────────────────────

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // Replicates nice_repr(timedelta(seconds=X), 'noday') from Python.
    function fmtTime(seconds) {
        seconds = Math.max(0, Math.floor(seconds));
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        var s = seconds % 60;
        return pad2(h) + ':' + pad2(m) + ':' + pad2(s);
    }

    function pad2(n) {
        return n < 10 ? '0' + n : String(n);
    }

    // Replicates Django's floatformat(pts, -precision).
    function fmtPoints(pts, precision) {
        if (pts === null || pts === undefined) return '0';
        if (precision === 0) return String(Math.round(pts));
        return parseFloat(parseFloat(pts).toFixed(precision)).toString();
    }

    // Returns the base CSS state class for a score.
    function baseStateClass(pts, maxPts) {
        if (!pts) return 'failed-score';
        if (pts === maxPts) return 'full-score';
        return 'partial-score';
    }

    // ─── First-solve / Total-AC computation ──────────────────────────────────

    function computeFirstSolvesAndTotalAC(participations, problems, contest) {
        var firstSolves = {};
        var totalAC = {};
        var cfg = contest.format_config || {};

        // Legacy IOI suppresses first-solve when time display is off.
        var suppressFirstSolve = (contest.format === 'ioi' || contest.format === 'ioi16') &&
                                 !cfg.cumtime && !cfg.last_score_altering;

        for (var pi = 0; pi < problems.length; pi++) {
            var problem = problems[pi];
            var pid = String(problem.id);
            firstSolves[pid] = null;
            totalAC[pid] = 0;
            var minTime = null;

            for (var ri = 0; ri < participations.length; ri++) {
                var p = participations[ri];
                var entry = (p.format_data || {})[pid];
                if (!entry) continue;

                var pts = entry.points || 0;
                var t   = entry.time   || 0;

                if (pts === problem.points) {
                    totalAC[pid]++;
                    if (!suppressFirstSolve && p.virtual === 0 && (minTime === null || t < minTime)) {
                        minTime = t;
                        firstSolves[pid] = p.id;
                    }
                }
            }
        }

        return { firstSolves: firstSolves, totalAC: totalAC };
    }

    // ─── Shared rendering helpers ────────────────────────────────────────────

    function makeSubmissionUrl(meta, problemCode) {
        if (meta.ghost || !meta.contest.url_templates) return null;
        return meta.contest.url_templates.problem_submissions
            .replace('__USERNAME__', meta.username)
            .replace('__PROBLEM__', problemCode);
    }

    function makeAllSubmissionsUrl(meta) {
        if (meta.ghost || !meta.contest.url_templates) return null;
        return meta.contest.url_templates.all_submissions
            .replace('__USERNAME__', meta.username);
    }

    // Returns the pretest CSS prefix for a problem cell.
    function pretestPrefix(meta, problem) {
        return (meta.contest.run_pretests_only && problem.is_pretested) ? 'pretest-' : '';
    }

    // Builds the state CSS class string common to all problem cells.
    function problemStateClass(entry, problem, isFirst, meta, extraPrefix) {
        return (extraPrefix || '') +
               pretestPrefix(meta, problem) +
               (isFirst ? 'first-solve ' : '') +
               baseStateClass(entry.points, problem.points);
    }

    // Wraps inner HTML in a standard problem <td><a>...</a></td>.
    function wrapProblemCell(state, url, innerHtml) {
        if (!url) return '<td class="' + state + '">' + innerHtml + '</td>';
        return '<td class="' + state + '"><a href="' + escapeHtml(url) + '">' +
               innerHtml + '</a></td>';
    }

    // Standard result cell: score with optional cumtime.
    function standardResultCell(participation, meta, showTime) {
        var url = makeAllSubmissionsUrl(meta);
        var inner = escapeHtml(fmtPoints(participation.score, meta.contest.points_precision)) +
            '<div class="solving-time">' +
            (showTime !== false ? escapeHtml(fmtTime(participation.cumtime)) : '') +
            '</div>';
        if (!url) return '<td class="user-points">' + inner + '</td>';
        return '<td class="user-points"><a href="' + escapeHtml(url) + '">' + inner + '</a></td>';
    }

    // Standard problem cell: points + optional extra HTML + time.
    // Used by default, atcoder, ecoo, legacy-ioi, and vnoj (non-pending).
    function standardProblemCell(entry, problem, participationId, firstSolves, meta, opts) {
        if (!entry) return '<td></td>';
        var pid = String(problem.id);
        var isFirst = firstSolves[pid] === participationId;
        var url = makeSubmissionUrl(meta, problem.code);

        var pointsHtml = escapeHtml(fmtPoints(entry.points, meta.contest.points_precision));
        var extraHtml = opts && opts.extraHtml ? opts.extraHtml : '';
        var showTime = !(opts && opts.showTime === false);
        var timeHtml = showTime ? escapeHtml(fmtTime(entry.time)) : '';
        var wrapDiv = opts && opts.wrapDiv;

        var inner = wrapDiv
            ? '<div>' + pointsHtml + extraHtml + '</div>'
            : pointsHtml + extraHtml;
        inner += '<div class="solving-time">' + timeHtml + '</div>';

        var state = problemStateClass(entry, problem, isFirst, meta);
        return wrapProblemCell(state, url, inner);
    }

    // Builds a red penalty annotation: " (N)"
    function penaltyHtml(value) {
        if (!value) return '';
        return '<small style="color:red"> (' + escapeHtml(fmtPoints(value, 0)) + ')</small>';
    }

    // ─── Format renderers ─────────────────────────────────────────────────────
    // Each renderer provides:
    //   renderProblemCell(entry, problem, participationId, firstSolves, meta)
    //   renderResultCell(participation, meta)

    // ── Default ──────────────────────────────────────────────────────────────
    var defaultRenderer = {
        renderProblemCell: function (entry, problem, participationId, firstSolves, meta) {
            return standardProblemCell(entry, problem, participationId, firstSolves, meta);
        },
        renderResultCell: function (participation, meta) {
            return standardResultCell(participation, meta);
        },
    };

    // ── Legacy IOI (ioi) ─────────────────────────────────────────────────────
    var legacyIoiRenderer = {
        renderProblemCell: function (entry, problem, participationId, firstSolves, meta) {
            var cfg = meta.contest.format_config || {};
            var showTime = cfg.cumtime || cfg.last_score_altering;
            return standardProblemCell(entry, problem, participationId, firstSolves, meta, {
                showTime: !!showTime,
            });
        },
        renderResultCell: function (participation, meta) {
            var cfg = meta.contest.format_config || {};
            var showTime = cfg.cumtime || cfg.last_score_altering;
            return standardResultCell(participation, meta, !!showTime);
        },
    };

    // ── IOI 2016+ (ioi16) ────────────────────────────────────────────────────
    var ioiRenderer = legacyIoiRenderer;

    // ── AtCoder ───────────────────────────────────────────────────────────────
    var atcoderRenderer = {
        renderProblemCell: function (entry, problem, participationId, firstSolves, meta) {
            return standardProblemCell(entry, problem, participationId, firstSolves, meta, {
                extraHtml: penaltyHtml(entry && entry.penalty),
            });
        },
        renderResultCell: defaultRenderer.renderResultCell,
    };

    // ── VNOJ ──────────────────────────────────────────────────────────────────
    var vnojRenderer = {
        renderProblemCell: function (entry, problem, participationId, firstSolves, meta) {
            if (!entry) return '<td></td>';
            var pending = entry.pending || 0;

            if (!pending) {
                return standardProblemCell(entry, problem, participationId, firstSolves, meta, {
                    extraHtml: penaltyHtml(entry.penalty),
                    wrapDiv: true,
                });
            }

            // Pending path: post-freeze submissions hidden
            var pid = String(problem.id);
            var isFirst = firstSolves[pid] === participationId;
            var url = makeSubmissionUrl(meta, problem.code);
            var state = problemStateClass(entry, problem, isFirst, meta, 'pending ');

            var pendingBadge = '<small style="color:black;"> [' + escapeHtml(String(pending)) + ']</small>';
            var ptsStr = (!entry.points && !entry.penalty)
                ? '?'
                : escapeHtml(fmtPoints(entry.points, meta.contest.points_precision)) + '?';

            return wrapProblemCell(state, url,
                '<div>' + ptsStr + pendingBadge + '</div>' +
                '<div class="solving-time">?</div>');
        },
        renderResultCell: defaultRenderer.renderResultCell,
    };

    // ── ECOO ──────────────────────────────────────────────────────────────────
    var ecooRenderer = {
        renderProblemCell: function (entry, problem, participationId, firstSolves, meta) {
            var bonusHtml = (entry && entry.bonus)
                ? '<small> +' + escapeHtml(fmtPoints(entry.bonus, 0)) + '</small>'
                : '';
            return standardProblemCell(entry, problem, participationId, firstSolves, meta, {
                extraHtml: bonusHtml,
            });
        },
        renderResultCell: function (participation, meta) {
            var cfg = meta.contest.format_config || {};
            return standardResultCell(participation, meta, !!cfg.cumtime);
        },
    };

    var RENDERERS = {
        'default':    defaultRenderer,
        'ioi':        legacyIoiRenderer,
        'ioi16':      ioiRenderer,
        'atcoder':    atcoderRenderer,
        'vnoj':       vnojRenderer,
        'ecoo':       ecooRenderer,
    };

    function buildTotalACRow(problems, totalAC, colspan, hasRating) {
        var html = '<tr><td colspan="' + colspan + '">Total AC</td>';
        for (var i = 0; i < problems.length; i++) {
            var prob = problems[i];
            var pid = String(prob.id);
            var label = escapeHtml(prob.label);
            html += '<td class="total-ac" id="' + label + '-total">' +
                escapeHtml(String(totalAC[pid] || 0)) + '</td>';
        }
        if (hasRating) html += '<td></td>';
        html += '</tr>';
        return html;
    }

    function replayUserCell(p, pinLabel) {
        var name = escapeHtml(p.name);
        var org = p.org ? '<span class="organization"><a data-org="' + escapeHtml(p.org.name) + '" href="' +
            escapeHtml(p.org.url) + '">' + escapeHtml(p.org.name) + '</a></span>' : '';
        return '<td class="user-name"><div><div class="usr-ranking-left" style="float:left"><div>' +
            '<i class="fav-button fa fa-heart fa-heart-o" data-username="' + name +
            '" role="button" tabindex="0" aria-label="' + escapeHtml(pinLabel) + ' · ' + name + '"></i>' +
            '<span class="' + escapeHtml(p.css_class) + '"><a href="' + escapeHtml(p.user_url) + '">' +
            escapeHtml(p.display_name) + '</a></span>' +
            (p.virtual ? '<sup class="virtual-participation">[' + p.virtual + ']</sup>' : '') +
            '<div class="personal-info">' + escapeHtml(p.full_name) + '</div></div></div>' +
            '<div style="float:right"><div class="personal-info">' + org + '</div></div></div></td>';
    }

    window.createReplayRenderer = function (container) {
        var standings = container.querySelector('#ranking-table');
        var identities = new Map(), ratings = new Map();
        standings.querySelectorAll('tbody tr[data-participation-id]').forEach(function (row) {
            var id = Number(row.dataset.participationId);
            identities.set(id, row.querySelector('.user-name').outerHTML);
            var rating = row.querySelector('.rating-column');
            if (rating) ratings.set(id, rating.outerHTML);
        });

        return function (data, newRoster) {
            if (!data) {
                container.replaceChildren(standings);
            } else {
                var contest = data.contest, problems = data.problems, parts = data.participations;
                var renderer = RENDERERS[contest.format];
                var result = computeFirstSolvesAndTotalAC(parts, problems, contest);
                var rows = [];
                for (var i = 0; i < parts.length; i++) {
                    var p = parts[i], meta = { contest: contest, username: p.name };
                    var nameCell = identities.get(p.id) || replayUserCell(p, container.dataset.pinLabel);
                    var cells = ['<tr id="user-' + escapeHtml(p.name) + '" data-participation-id="' + p.id +
                        '"' + (p.is_disqualified ? ' class="disqualified"' : '') + '><td>' + p.rank + '</td>', nameCell,
                        renderer.renderResultCell(p, meta)];
                    for (var j = 0; j < problems.length; j++) {
                        var prob = problems[j];
                        cells.push(renderer.renderProblemCell(p.format_data[prob.id], prob, p.id, result.firstSolves, meta));
                    }
                    if (contest.has_rating) cells.push(ratings.get(p.id) || '<td class="rating-column"></td>');
                    cells.push('</tr>');
                    rows.push(cells.join(''));
                }
                var table = standings.cloneNode(false);
                delete table.dataset.filtered;
                table.appendChild(standings.tHead.cloneNode(true));
                table.createTBody().innerHTML = rows.join('') + buildTotalACRow(problems, result.totalAC, 3, contest.has_rating);
                container.replaceChildren(table);
            }
            window.onRankingTableChanged(newRoster);
        };
    };

})(jQuery);
