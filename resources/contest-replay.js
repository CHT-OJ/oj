(function () {
    'use strict';
    const data = JSON.parse(document.getElementById('replay-data').textContent);
    const slider = document.getElementById('replay-time');
    const table = document.getElementById('ranking-table');
    const play = document.getElementById('replay-play');
    const follow = document.getElementById('follow-virtual');
    const playLabel = play.textContent;
    const duration = Math.ceil(data.duration);
    let serverTime = data.elapsed;
    let synced = Date.now();
    let playing = false;
    let lastPosition = -1;
    function clock(sec) {
        sec = Math.floor(sec);
        return [Math.floor(sec / 3600), Math.floor(sec / 60) % 60, sec % 60]
            .map(n => String(n).padStart(2, '0')).join(':');
    }
    function prepare(row) {
        row.cursor = 0;
        row.cells = new Array(data.problems.length).fill(null);
        row.total = row.time = row.tie = 0;
    }
    function render(position) {
        const rows = Object.values(data.rows);
        let changed = false;
        rows.forEach(row => {
            if (position < lastPosition || row.cursor === undefined) {
                prepare(row);
                changed = true;
            }
            while (row.cursor < row.events.length && row.events[row.cursor][0] <= position) {
                const [, index, points, total, time, tie] = row.events[row.cursor++];
                changed = true;
                row.cells[index] = points;
                row.total = total;
                row.time = time;
                row.tie = tie;
            }
        });
        slider.value = position;
        document.getElementById('replay-clock').textContent = clock(position);
        lastPosition = position;
        if (!changed) return;
        function compare(a, b) {
            if (a.dq !== b.dq) return Number(a.dq) - Number(b.dq);
            if (a.dq) return 0;
            return b.total - a.total || a.time - b.time || a.tie - b.tie;
        }
        rows.sort((a, b) => compare(a, b) || b.cursor - a.cursor || a.name.localeCompare(b.name));
        const body = document.createDocumentFragment();
        let rank = 0;
        rows.forEach((row, i) => {
            if (!i || compare(row, rows[i - 1])) rank = i + 1;
            const tr = document.createElement('tr');
            tr.dataset.contestUser = row.name;
            if (row.dq) tr.className = 'disqualified';
            function cell(value, cls) {
                const td = tr.insertCell();
                td.textContent = value;
                if (cls) td.className = cls;
            }
            cell(rank);
            cell(row.name + (row.virtual ? ' (' + table.dataset.virtual + ')' : ''), 'user-name');
            cell(row.dq ? 'DQ' : row.total, 'user-points');
            cell(row.dq ? '—' : clock(row.time));
            row.cells.forEach(points => cell(points === null ? '—' : points));
            body.append(tr);
        });
        table.tBodies[0].replaceChildren(body);
        document.dispatchEvent(new Event('ranking-updated'));
    }
    function stop() { playing = false; play.textContent = playLabel; }
    data.problems.forEach(label => {
        const th = document.createElement('th');
        th.textContent = label;
        table.tHead.rows[0].append(th);
    });
    slider.max = duration;
    slider.addEventListener('input', () => { stop(); follow.checked = false; render(+slider.value); });
    play.addEventListener('click', () => {
        follow.checked = false;
        if (playing) { stop(); return; }
        if (+slider.value >= duration) render(0);
        playing = true;
        play.textContent = table.dataset.pause;
    });
    if (serverTime !== null) {
        document.getElementById('live-controls').hidden = false;
        follow.addEventListener('change', stop);
        async function sync() {
            try {
                const response = await fetch('?own=1', {credentials: 'same-origin'});
                if (response.status === 204) { location.reload(); return; }
                if (response.ok) {
                    const update = await response.json();
                    Object.assign(data.rows, update.rows);
                    serverTime = update.elapsed;
                    synced = Date.now();
                    render(+slider.value);
                }
            } catch (error) {
                // Keep the last complete standings during a temporary connection loss.
            } finally { setTimeout(sync, 20000); }
        }
        setTimeout(sync, 20000);
    }
    render(Math.floor(serverTime || 0));
    setInterval(() => {
        if (document.hidden) return;
        let next = +slider.value;
        if (serverTime !== null && follow.checked) next = Math.floor(serverTime + (Date.now() - synced) / 1000);
        else if (playing) next += Math.max(1, Math.ceil(duration / 180));
        next = Math.min(duration, next);
        if (next !== lastPosition) render(next);
        if (next === duration) stop();
    }, 1000);
})();
