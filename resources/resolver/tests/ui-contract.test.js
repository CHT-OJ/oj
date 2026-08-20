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
