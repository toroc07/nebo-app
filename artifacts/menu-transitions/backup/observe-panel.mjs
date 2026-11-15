import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const out = new URL("../../../artifacts/observe-menu/", import.meta.url)
  .pathname;
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
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const url = process.env.NEBO_TEST_URL || "http://localhost:3002";
await page.goto(url);
await page.waitForFunction(() => document.documentElement.dataset.theme);
assert.notEqual(
  await page.locator(".primary-tile .panel-image").first().getAttribute("src"),
  "/horizon.webp",
);
await page.getByRole("button", { name: /Start exploring/ }).click();
await page.getByRole("navigation", { name: "Observe panel" }).waitFor();
// The entrance is observable, then fully clears its inline styles.
const entering = await page
  .locator(".observe-grid .image-tile")
  .evaluateAll((cards) =>
    cards.map((el) => Number(getComputedStyle(el).opacity)),
  );
assert.ok(
  entering.some((value) => value < 1),
  "entrance fades the cards",
);
await page.waitForFunction(() =>
  [...document.querySelectorAll(".observe-grid .tile-bottom")].every(
    (el) => !el.style.transform && !el.style.opacity,
  ),
);
assert.equal(await page.locator(".observe-grid .image-tile").count(), 2);
assert.equal(
  await page.getByText("01 / NO SET COURSE", { exact: true }).count(),
  0,
);
assert.equal(await page.locator(".coordinate-art").count(), 0);
assert.equal(
  new Set(
    await page
      .locator(".observe-grid .panel-image:not(.panel-image-sharp)")
      .evaluateAll((images) => images.map((i) => i.src)),
  ).size,
  2,
);
await page.mouse.move(0, 0);
await page.waitForTimeout(500);
await page.screenshot({ path: out + "observe-rest.png", fullPage: true });
for (const selector of [".start-tile", ".coordinate-tile"]) {
  const tile = page.locator(selector);
  const sharp = tile.locator(".panel-image-sharp");
  assert.equal(await sharp.evaluate((el) => getComputedStyle(el).opacity), "0");
  const box = await tile.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y - 4);
  assert.equal(await tile.getAttribute("data-near"), "true");
  await tile.hover();
  await page.waitForTimeout(500);
  assert.equal(await sharp.evaluate((el) => getComputedStyle(el).opacity), "1");
  assert.equal(
    await tile.evaluate((el) => getComputedStyle(el, "::after").opacity),
    "1",
  );
  assert.notEqual(
    await tile
      .locator(".tile-link svg")
      .evaluate((el) => getComputedStyle(el).transform),
    "none",
  );
  await page.screenshot({
    path: out + selector.slice(1) + "-hover.png",
    fullPage: true,
  });
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
}
// Repeated navigation must cancel old timelines rather than leave cards invisible.
for (let i = 0; i < 4; i++) {
  await page.getByRole("link", { name: "Nebo, home" }).click({ force: true });
  await page
    .getByRole("button", { name: /Start exploring/ })
    .click({ force: true });
}
await page.waitForTimeout(600);
assert.ok(
  await page
    .locator(".observe-grid .image-tile")
    .evaluateAll((cards) =>
      cards.every((el) => getComputedStyle(el).opacity === "1"),
    ),
);
const stress = [];
for (const [width, height] of [
  [320, 568],
  [375, 812],
  [568, 320],
  [768, 1024],
  [1280, 800],
  [1920, 1080],
]) {
  await page.setViewportSize({ width, height });
  const margins = await page.locator(".observe-grid").evaluate((el) => {
    const r = el.getBoundingClientRect();
    return [r.left, innerWidth - r.right];
  });
  assert.ok(Math.abs(margins[0] - margins[1]) < 1);
  for (const size of ["100%", "200%", "400%"]) {
    await page.evaluate(
      (size) => (document.documentElement.style.fontSize = size),
      size,
    );
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    assert.ok(
      await page
        .locator(".observe-grid .image-tile")
        .evaluateAll((cards) =>
          cards.every((el) => el.scrollWidth <= el.clientWidth + 1),
        ),
    );
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
  stress.push({ width, height, margins });
}
// Both destinations and the return action work using only the keyboard at 375px.
await page.setViewportSize({ width: 375, height: 812 });
await page.getByRole("link", { name: "Nebo, home" }).click();
await page.getByRole("button", { name: /Start exploring/ }).click();
await page.keyboard.press("Tab");
assert.equal(
  await page.evaluate(() =>
    document.activeElement.classList.contains("start-tile"),
  ),
  true,
);
await page.keyboard.press("Tab");
assert.equal(
  await page.evaluate(() =>
    document.activeElement.classList.contains("coordinate-tile"),
  ),
  true,
);
await page.keyboard.press("Enter");
await page.getByLabel("Right ascension").waitFor();
await page.keyboard.press("Tab");
assert.equal(await page.evaluate(() => document.activeElement.id), "ra");
await page.keyboard.press("Shift+Tab");
assert.equal(
  await page.evaluate(() => document.activeElement.textContent.trim()),
  "Back",
);
await page.keyboard.press("Enter");
await page.keyboard.press("Tab");
await page.keyboard.press("Enter");
await page.waitForURL("**/lab/observation");
await page.goBack();
await page.getByRole("button", { name: /Start exploring/ }).click();
await page.waitForTimeout(600);
await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" });
const axe = {};
for (const scheme of ["light", "dark"]) {
  await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
  axe[scheme] = await page.evaluate(async () =>
    (await window.axe.run()).violations.map((v) => ({
      id: v.id,
      targets: v.nodes.map((n) => n.target),
    })),
  );
  assert.deepEqual(axe[scheme], []);
}
// Snapshot is rendered DOM with scripts removed; the audit proxy serves its real assets.
await page.setViewportSize({ width: 1280, height: 800 });
await page.mouse.move(0, 0);
await page.screenshot({ path: out + "observe-final.png", fullPage: true });
writeFileSync(
  out + "observe.html",
  (await page.content()).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ""),
);
const touch = await browser.newPage({
  viewport: { width: 375, height: 812 },
  isMobile: true,
  hasTouch: true,
  reducedMotion: "reduce",
});
await touch.goto(url);
await touch.waitForFunction(() => document.documentElement.dataset.theme);
await touch.getByRole("button", { name: /Start exploring/ }).tap();
assert.ok(
  await touch
    .locator(".observe-grid .panel-image-sharp")
    .evaluateAll((images) =>
      images.every((el) => getComputedStyle(el).opacity === "1"),
    ),
);
await touch.getByRole("button", { name: /Search by coordinates/ }).tap();
await touch.getByLabel("Right ascension").waitFor();
await touch.close();
assert.deepEqual(errors, []);
writeFileSync(
  out + "interaction-results.json",
  JSON.stringify(
    {
      passed: true,
      entering,
      stress,
      hover: true,
      proximity: true,
      keyboard: true,
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
console.log("Observe menu interactions passed");
