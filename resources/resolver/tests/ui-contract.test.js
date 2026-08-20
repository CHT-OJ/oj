import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("award configuration does not permanently recolor ranking rows", async () => {
  const [css, page] = await Promise.all([
    readFile(new URL("../resolver.css", import.meta.url), "utf8"),
    readFile(new URL("../page.js", import.meta.url), "utf8"),
  ]);
  assert.equal(css.includes("resolver-row--award"), false);
  assert.equal(page.includes("resolver-row--award"), false);
  assert.equal(page.includes("resolver-row--award-first"), false);
});

test("avatar and logo visuals keep separate shapes", async () => {
  const css = await readFile(new URL("../resolver.css", import.meta.url), "utf8");
  assert.match(css, /\.resolver-contestant__avatar\s*\{[^}]*border-radius:\s*50%/s);
  assert.match(
    css,
    /\.resolver-contestant__identity \.resolver-contestant__visual--logo\s*\{[^}]*border-radius:\s*0\.15rem/s,
  );
  assert.match(css, /\.resolver-contestant__visual--logo img\s*\{[^}]*object-fit:\s*contain/s);
});

test("presenter setup keeps engine details advanced and the HUD hidden by default", async () => {
  const template = await readFile(
    new URL("../../../templates/contest/spotlight-ranking.html", import.meta.url),
    "utf8",
  );
  assert.match(template, /id="resolver-autoplay"[^>]*checked/);
  assert.match(template, /id="resolver-advanced"[^>]*class="resolver-advanced"/);
  assert.match(template, /id="resolver-hud"[^>]*hidden/);
  assert.match(template, /id="resolver-tie-order"[^>]*type="hidden"[^>]*value="seeded"/);
  assert.equal(template.includes("data-resolver-preset"), false);
});

test("dynamic Resolver rendering does not inject translated or user data as HTML", async () => {
  const [page, bootstrap] = await Promise.all([
    readFile(new URL("../page.js", import.meta.url), "utf8"),
    readFile(new URL("../bootstrap.js", import.meta.url), "utf8"),
  ]);
  assert.equal(page.includes("innerHTML"), false);
  assert.equal(page.includes("insertAdjacentHTML"), false);
  assert.equal(bootstrap.includes("innerHTML"), false);
  assert.match(page, /document\.createTextNode/);
});

test("problem and contestant bulk controls use one semantic batch operation", async () => {
  const page = await readFile(new URL("../page.js", import.meta.url), "utf8");
  assert.match(page, /dataset\.resolverAction = "reveal-problem"/);
  assert.match(page, /getResolvableCellsForProblem/);
  assert.match(page, /getResolvableCellsForContestant/);
  assert.match(page, /session\.revealBatch\(targets\)/);
  assert.match(page, /!event\.target\.closest\("a"\)/);
});

test("ranking renders with stable participation rows instead of rebuilding the table body", async () => {
  const page = await readFile(new URL("../page.js", import.meta.url), "utf8");
  assert.match(page, /this\.rowElements = new Map\(\)/);
  assert.match(page, /this\.rowElements\.get\(contestantId\)/);
  assert.match(page, /_reorderTableBody\(\[\.\.\.rows, this\._updateTotals\(stats\)\]\)/);
  assert.equal(page.includes("tableBody.replaceChildren(...rows"), false);
});
