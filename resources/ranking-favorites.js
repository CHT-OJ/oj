/* VNOI-Admin/OJ #727, with migration of pins saved by earlier CHTOJ PR builds. */
(function ($) {
    'use strict';
    window.initRankingFavorites = function (contest_key) {
        // Stored as JSON so usernames containing commas survive. Older pages
        // saved a comma-joined string, so fall back to splitting that.
        function getFavoriteUsers() {
            let fav_users = localStorage.getItem(`favorite-users-${contest_key}`) ??
                localStorage.getItem(`ranking-favorites:${contest_key}`);
            if (!fav_users) return [];
            try {
                let parsed = JSON.parse(fav_users);
                if (Array.isArray(parsed)) return parsed;
            } catch (e) {}
            return fav_users.split(',');
        }

        // Pin a copy of each favorite user's row to the top of the table. The
        // copies have no id, so the organization filter only sees the originals.
        window.applyFavoriteUsers = function () {
            let fav_users = new Set(getFavoriteUsers());
            let $tbody = $('#ranking-table > tbody');
            $tbody.children('tr.favorite').remove();

            let pinned = [];
            $tbody.children('tr[id]').each(function () {
                let row = $(this);
                let fav_button = row.find('.fav-button');
                let is_fav = fav_users.has(fav_button.attr('data-username'));
                fav_button.toggleClass('fa-heart-o', !is_fav).attr('aria-pressed', String(is_fav));
                if (is_fav) {
                    let copy = row.clone().removeAttr('id').addClass('favorite').show();
                    copy.find('[id]').removeAttr('id');
                    pinned.push(copy);
                }
            });

            if (pinned.length) {
                pinned[pinned.length - 1].addClass('last-favorite');
                $tbody.prepend(pinned);
            }
        };

        $('#ranking-container').on('keydown', '.fav-button', function (event) {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                $(this).trigger('click');
            }
        }).on('click', '.fav-button', function () {
            let user_name = $(this).attr('data-username');
            let fav_users = getFavoriteUsers().filter(x => x !== user_name);
            if ($(this).hasClass('fa-heart-o')) {
                fav_users.push(user_name);
            }
            localStorage.setItem(`favorite-users-${contest_key}`, JSON.stringify(fav_users));
            let wasPinnedRow = $(this).closest('tr').hasClass('favorite');
            window.applyFavoriteUsers();
            if (wasPinnedRow) {
                $('#ranking-table tr[id] .fav-button').filter(function () {
                    return this.dataset.username === user_name && $(this).is(':visible');
                }).first().trigger('focus');
            }
        });
    };
})(jQuery);
