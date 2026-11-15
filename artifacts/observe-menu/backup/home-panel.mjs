import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const out = new URL("../../../artifacts/panel-home/", import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox"],
});
const page = await browser.newPage({
  viewport: { width: 1280, height: 800 },
  reducedMotion: "no-preference",
  colorScheme: "dark",
});
const url = process.env.NEBO_TEST_URL || "http://localhost:3002";
await page.route("**/api/v1/**", (r) =>
  r.fulfill({ json: [], headers: { "Access-Control-Allow-Origin": "*" } }),
);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(url);
await page.waitForFunction(() => document.documentElement.dataset.theme);
const tile = page.locator(".primary-tile");
const sharp = tile.locator(".panel-image-sharp");
await page.mouse.move(0, 0);
await page.waitForTimeout(300);
assert.equal(await sharp.evaluate((el) => getComputedStyle(el).opacity), "0");
const box = await tile.boundingBox();
await page.mouse.move(box.x + box.width / 2, box.y - 4);
assert.equal(await tile.getAttribute("data-near"), "true");
await page.waitForTimeout(300);
assert.equal(await sharp.evaluate((el) => getComputedStyle(el).opacity), "0");
await tile.hover();
await page.waitForTimeout(300);
assert.equal(await sharp.evaluate((el) => getComputedStyle(el).opacity), "1");
assert.notEqual(
  await tile.evaluate((el) => getComputedStyle(el).transform),
  "none",
);
assert.equal(
  await tile.evaluate((el) => getComputedStyle(el, "::after").opacity),
  "1",
);
await page.screenshot({ path: out + "hover-desktop.png", fullPage: true });
await page.mouse.move(0, 0);
await page.waitForTimeout(300);
assert.equal(await sharp.evaluate((el) => getComputedStyle(el).opacity), "0");
await page.screenshot({ path: out + "rest-desktop.png", fullPage: true });
// All destinations are reached from the panel, using actual Tab / Enter only.
const tasks = [];
await page.setViewportSize({ width: 375, height: 812 });
for (const [label, heading] of [
  ["Start exploring", "Observe"],
  ["Featured objects", "Featured objects"],
  ["Tutorial", "Tutorial"],
]) {
  await page.reload();
  await page.waitForFunction(() => document.documentElement.dataset.theme);
  let tabs = 0;
  for (; tabs < 12; tabs++) {
    await page.keyboard.press("Tab");
    if (
      await page.evaluate(
        (label) =>
          document.activeElement?.tagName === "BUTTON" &&
          document.activeElement.textContent.includes(label),
        label,
      )
    )
      break;
  }
  assert.ok(tabs < 12, "keyboard destination: " + label);
  assert.equal(
    await page.evaluate(
      () => getComputedStyle(document.activeElement).outlineStyle,
    ),
    "solid",
  );
  await page.keyboard.press("Enter");
  await page
    .getByRole("heading", { level: 1, name: heading, exact: true })
    .waitFor();
  await page.keyboard.press("Shift+Tab");
  assert.equal(
    await page.evaluate(() => document.activeElement.textContent.trim()),
    "Back",
  );
  await page.keyboard.press("Enter");
  await page.getByRole("navigation", { name: "Home panel" }).waitFor();
  tasks.push({ label, tabs: tabs + 1, enter: true, return: true });
}
const stress = [];
for (const width of [320, 375, 568, 1280]) {
  await page.setViewportSize({ width, height: width === 568 ? 320 : 812 });
  for (const size of ["140%", "200%", "400%"]) {
    await page.evaluate(
      (size) => (document.documentElement.style.fontSize = size),
      size,
    );
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `${width}px / ${size}`,
    );
    // Detect clipping inside the shell, too.
    assert.ok(
      await page
        .locator(".image-tile")
        .evaluateAll((tiles) =>
          tiles.every((tile) => tile.scrollWidth <= tile.clientWidth + 1),
        ),
      `card content: ${width}px / ${size}`,
    );
    stress.push({ width, size });
  }
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "100%";
    document.documentElement.dir = "rtl";
  });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page.evaluate(() => (document.documentElement.dir = "ltr"));
}
await page.setViewportSize({ width: 1280, height: 800 });
await page.emulateMedia({ reducedMotion: "reduce" });
await tile.hover();
assert.equal(
  await tile.evaluate((el) => getComputedStyle(el).transform),
  "none",
);
// Touch gets clear images and opens on the first tap.
const touch = await browser.newPage({
  viewport: { width: 375, height: 812 },
  hasTouch: true,
  isMobile: true,
  reducedMotion: "reduce",
});
await touch.goto(url);
await touch.waitForFunction(() => document.documentElement.dataset.theme);
assert.equal(
  await touch
    .locator(".primary-tile .panel-image-sharp")
    .evaluate((el) => getComputedStyle(el).opacity),
  "1",
);
await touch.getByRole("button", { name: /Start exploring/ }).tap();
await touch
  .getByRole("heading", { level: 1, name: "Observe", exact: true })
  .waitFor();
await touch.close();
await page.mouse.move(0, 0);
await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" });
const axe = {};
for (const colorScheme of ["light", "dark"]) {
  await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
  axe[colorScheme] = await page.evaluate(async () =>
    (await window.axe.run()).violations.map((v) => ({
      id: v.id,
      targets: v.nodes.map((n) => n.target),
    })),
  );
  assert.deepEqual(axe[colorScheme], []);
}
assert.deepEqual(errors, []);
writeFileSync(
  out + "interaction-results.json",
  JSON.stringify(
    {
      tasks,
      stress,
      hover: true,
      proximity: true,
      touch: true,
      reducedMotion: true,
      axe,
      errors,
    },
    null,
    2,
  ),
);
await browser.close();
console.log("Home panel interactions passed");
