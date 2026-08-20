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
});
