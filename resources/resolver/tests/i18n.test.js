import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { gettext, ngettext } from "../i18n.js";

test("Resolver i18n has an English fallback and supports runtime Vietnamese gettext", () => {
  const originalGettext = globalThis.gettext;
  const originalNgettext = globalThis.ngettext;
  try {
    delete globalThis.gettext;
    delete globalThis.ngettext;
    assert.equal(gettext("Play"), "Play");
    assert.equal(ngettext("%(count)s cell", "%(count)s cells", 2), "2 cells");

    const messages = new Map([
      ["Play", "Chạy"],
      ["Reveal problem %(problem)s", "Mở toàn bộ kết quả bài %(problem)s"],
    ]);
    globalThis.gettext = (message) => messages.get(message) ?? message;
    globalThis.ngettext = (singular) => singular;
    assert.equal(gettext("Play"), "Chạy");
    assert.equal(
      gettext("Reveal problem %(problem)s", { problem: "A" }),
      "Mở toàn bộ kết quả bài A",
    );
  } finally {
    if (originalGettext === undefined) {
      delete globalThis.gettext;
    } else {
      globalThis.gettext = originalGettext;
    }
    if (originalNgettext === undefined) {
      delete globalThis.ngettext;
    } else {
      globalThis.ngettext = originalNgettext;
    }
  }
});

test("Vietnamese Resolver catalog contains essential dynamic controls", async () => {
  const catalog = await readFile(
    new URL("../../../locale/vi/LC_MESSAGES/djangojs.po", import.meta.url),
    "utf8",
  );
  assert.match(catalog, /msgid "Play"\s+msgstr "Chạy"/);
  assert.match(catalog, /msgid "Pause"\s+msgstr "Tạm dừng"/);
  assert.match(
    catalog,
    /msgid "Reveal all results for this contestant"\s+msgstr "Mở toàn bộ kết quả của thí sinh"/,
  );
  assert.match(catalog, /msgid "Next"\s+msgstr "Tiếp theo"/);
  assert.match(catalog, /msgid "Resolver settings"\s+msgstr "Thiết lập trình diễn"/);
  assert.match(
    catalog,
    /msgid "The ceremony has reached the top %\(rank\)s award zone\."\s+msgstr "Phần trình diễn đã bắt đầu vào vùng giải thưởng Top %\(rank\)s\."/,
  );
  assert.match(
    catalog,
    /msgid "Official freeze is configured but has not started yet\."\s+msgstr "Official freeze đã được cấu hình nhưng chưa bắt đầu\."/,
  );
  assert.match(
    catalog,
    /msgid "This preview snapshot cannot be used as final results\. The contest may now have ended; refresh results to load a final snapshot\."\s+msgstr "Snapshot xem trước này không thể dùng làm kết quả cuối cùng\. Kỳ thi có thể đã kết thúc; hãy tải lại kết quả để lấy snapshot cuối cùng\."/,
  );
  assert.match(catalog, /msgid "Final results ready"\s+msgstr "Kết quả cuối cùng đã sẵn sàng"/);
  assert.match(
    catalog,
    /msgid "Snapshot safety information could not be verified"\s+msgstr "Không thể xác minh thông tin an toàn của snapshot"/,
  );
});
