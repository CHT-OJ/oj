/* Timeline, controls and ranking order ported from VNOI-Admin/OJ #658 (7900e2f80).
 * The server supplies CHTOJ scoring checkpoints, including IOI subtask results.
 */
(function ($) {
    'use strict';

    function sortAndRankParticipations(parts) {
        parts.sort(function (a, b) {
            var aDq = a.is_disqualified ? 1 : 0, bDq = b.is_disqualified ? 1 : 0;
            if (aDq !== bDq) return aDq - bDq;
            if (b.score !== a.score) return b.score - a.score;
            if (a.cumtime !== b.cumtime) return a.cumtime - b.cumtime;
            return a.tiebreaker - b.tiebreaker || b.submissionCount - a.submissionCount || a.id - b.id;
        });
        var rank = 0, delta = 1, lastKey = null;
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i];
            var key = (p.is_disqualified ? 1 : 0) + '|' + p.score + '|' + p.cumtime + '|' + p.tiebreaker;
            if (key !== lastKey) { rank += delta; delta = 0; }
            delta++;
            p.rank = rank;
            lastKey = key;
        }
    }

    function fmtHMS(s) {
        s = Math.floor(Math.max(0, s));
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        return (h ? h + ':' : '') + (h && m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec;
    }

    // Seek each participant's ordered checkpoints. Forward drags consume only new events.
    function standingsAt(data, elapsed, freezeSeconds, changed) {
        var parts = Object.values(data.rows);
        var freezeAt = data.duration - freezeSeconds;
        parts.forEach(function (p) {
            if (p.cursor === undefined || elapsed < p.position || p.freezeAt !== freezeAt) {
                changed = true;
                p.cursor = p.score = p.cumtime = p.tiebreaker = p.submissionCount = 0;
                p.format_data = {};
            }
            p.position = elapsed;
            p.freezeAt = freezeAt;
            while (p.cursor < p.events.length && p.events[p.cursor][0] <= elapsed) {
                var event = p.events[p.cursor++];
                var pid = event[1];
                changed = true;
                p.submissionCount += event[7] || 1;
                if (freezeSeconds > 0 && !p.virtual && event[0] >= freezeAt) {
                    var prev = p.format_data[pid] || { points: 0, penalty: 0 };
                    if (event[6] && prev.points < data.maximum[pid]) {
                        p.format_data[pid] = Object.assign({}, prev, { pending: (prev.pending || 0) + event[6] });
                    }
                } else {
                    p.format_data[pid] = event[2];
                    p.score = event[3];
                    p.cumtime = event[4];
                    p.tiebreaker = event[5];
                }
            }
            if (p.is_disqualified) {
                p.score = -9999;
                p.cumtime = p.tiebreaker = 0;
            }
        });
        if (!changed) return null;
        sortAndRankParticipations(parts);
        return { contest: data.contest, problems: data.problems, participations: parts };
    }

    window.initContestRanking = function (options, labels) {
        var container = document.getElementById('ranking-container');
        var render = window.createReplayRenderer(container);
        var duration = Math.ceil(options.duration);
        var isVirtual = options.own;
        var supportsFrozen = options.supports_frozen;
        var freezeKey = 'replay_freeze_' + options.url;
        var frozenOverride = supportsFrozen ? localStorage.getItem(freezeKey) : null;
        var $slider, $timeLabel, $freezeInput;
        var data = null, loading = false, frame = null;
        var manualElapsed = isVirtual ? null : duration;
        var syncedAt, showingReplay = false, rosterChanged = false;
        function updateBar(elapsed, duration) {
            if (!$slider) return;
            $slider.val(Math.floor(elapsed));
            $timeLabel.text(fmtHMS(elapsed) + ' / ' + fmtHMS(duration));
        }

        function createBar(duration) {
            var $bar = $('<div>').css({
                display: 'flex', alignItems: 'center', gap: '8px',
                padding: '6px 0', marginBottom: '8px', fontSize: '13px',
            });
            $slider = $('<input>').attr({ type: 'range', 'aria-label': labels.time, min: 0, max: Math.floor(duration), step: 1 })
                .css({ flex: '1', cursor: 'pointer' });
            $timeLabel = $('<span>').css({ minWidth: '110px', fontFamily: 'monospace' });
            var $endBtn = $('<button>').attr('type', 'button').text(isVirtual ? 'Live' : 'End').css({ fontSize: '12px', padding: '2px 8px' });
            if (supportsFrozen) {
                $freezeInput = $('<input>').attr({ type: 'number', min: 0, placeholder: 'Freeze min', 'aria-label': labels.freeze })
                    .css({ width: '90px', fontSize: '12px' });
                if (frozenOverride !== null) $freezeInput.val(frozenOverride);
            }
            $bar.append($('<span>').text('⏱'), $slider, $timeLabel, $endBtn);
            if ($freezeInput) $bar.append($freezeInput);
            $('#ranking-container').before($bar);
            return $endBtn;
        }


        function position() {
            return manualElapsed === null
                ? Math.min(duration, Math.max(0, Math.floor(data.elapsed + (Date.now() - syncedAt) / 1000)))
                : manualElapsed;
        }

        function tick() {
            frame = null;
            if (!data) return;
            var elapsed = position();
            updateBar(elapsed, duration);
            if (!isVirtual && elapsed === duration && !Number(frozenOverride)) {
                if (showingReplay) render(null, true);
                showingReplay = false;
            } else {
                var standings = standingsAt(data, elapsed, Number(frozenOverride) * 60, !showingReplay || rosterChanged);
                if (standings) render(standings, !showingReplay || rosterChanged);
                showingReplay = true;
                rosterChanged = false;
            }
        }

        function scheduleRender() {
            if (frame === null) frame = requestAnimationFrame(tick);
        }

        var $endBtn = createBar(duration);
        var $error = $('<span role="status">').insertAfter($endBtn).hide();
        updateBar(duration, duration);
        if (options.show_virtual && !isVirtual) {
            $slider.parent().addClass('replay-blocked').attr('title', labels.virtual)
                .find('input, button').prop('disabled', true);
            return;
        }

        function pollOwn() {
            $.getJSON(options.url, { own: 1 }).done(function (update, _, xhr) {
                if (xhr.status === 204) { window.location.reload(); return; }
                rosterChanged = Object.keys(update.rows).some(function (id) { return !data.rows[id]; });
                Object.keys(data.rows).forEach(function (id) {
                    if (data.rows[id].virtual) delete data.rows[id];
                });
                Object.assign(data.rows, update.rows);
                data.elapsed = update.elapsed;
                syncedAt = Date.now();
                scheduleRender();
            }).always(function () { setTimeout(pollOwn, 20000); });
        }

        function loadReplay() {
            if (data) { scheduleRender(); return; }
            if (loading) return;
            loading = true;
            $.getJSON(options.url, { data: 1 }).done(function (result) {
                if ((result.elapsed !== null) !== isVirtual) { window.location.reload(); return; }
                data = result;
                data.maximum = Object.fromEntries(data.problems.map(function (p) { return [p.id, p.points]; }));
                syncedAt = Date.now();
                $error.hide();
                scheduleRender();
                if (isVirtual) {
                    setTimeout(pollOwn, 20000);
                    setInterval(function () {
                        if (!document.hidden && manualElapsed === null && position() !== Number($slider.val())) {
                            scheduleRender();
                        }
                    }, 1000);
                }
            }).fail(function () {
                $error.text(labels.retry).show();
            }).always(function () { loading = false; });
        }

        $slider.on('input', function () {
            manualElapsed = Number(this.value);
            updateBar(manualElapsed, duration);
            loadReplay();
        });
        $endBtn.on('click', function () {
            manualElapsed = isVirtual ? null : duration;
            if (!data && !isVirtual && !Number(frozenOverride)) {
                updateBar(duration, duration);
                $error.hide();
            } else {
                loadReplay();
            }
        });
        if ($freezeInput) {
            $freezeInput.on('input', function () {
                var val = this.value.trim();
                frozenOverride = val === '' ? null : Math.max(0, parseInt(val, 10) || 0);
                if (frozenOverride === null) localStorage.removeItem(freezeKey);
                else localStorage.setItem(freezeKey, frozenOverride);
                loadReplay();
            });
        }
        if (isVirtual || Number(frozenOverride)) loadReplay();
    };
})(jQuery);
