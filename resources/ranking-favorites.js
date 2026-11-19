(function () {
    'use strict';
    const section = document.getElementById('ranking-favorites');
    if (!section) return;
    const key = 'ranking-favorites:' + section.dataset.key;
    let favorites = new Set();
    try {
        const stored = JSON.parse(localStorage.getItem(key));
        if (Array.isArray(stored)) favorites = new Set(stored);
    } catch (error) { /* Storage may be disabled. */ }

    function refresh() {
        const list = section.querySelector('ul');
        list.replaceChildren();
        document.querySelectorAll('#ranking-table tr[data-contest-user]').forEach(row => {
            const name = row.dataset.contestUser;
            let button = row.querySelector('.pin-participant');
            if (!button) {
                button = document.createElement('button');
                button.type = 'button';
                button.className = 'pin-participant';
                button.setAttribute('aria-label', section.dataset.label + ' · ' + name);
                button.title = button.getAttribute('aria-label');
                row.querySelector('.user-name').prepend(button);
            }
            const pinned = favorites.has(name);
            button.textContent = pinned ? '★' : '☆';
            button.setAttribute('aria-pressed', String(pinned));
            if (pinned && !row.hidden && row.style.display !== 'none') {
                const entry = document.createElement('li');
                entry.textContent = [row.cells[0].innerText, name, row.querySelector('.user-points').innerText].join(' · ');
                list.append(entry);
            }
        });
        section.hidden = !list.children.length;
    }
    document.addEventListener('click', event => {
        const button = event.target.closest('.pin-participant');
        if (!button) return;
        const name = button.closest('tr').dataset.contestUser;
        if (favorites.has(name)) favorites.delete(name);
        else favorites.add(name);
        try { localStorage.setItem(key, JSON.stringify(Array.from(favorites))); } catch (error) {}
        refresh();
    });
    document.addEventListener('ranking-updated', refresh);
    refresh();
})();
