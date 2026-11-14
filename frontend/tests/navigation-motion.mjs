import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const out = new URL("../../../artifacts/menu-transitions/", import.meta.url)
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
});
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(process.env.NEBO_TEST_URL || "http://localhost:3002");
await page.waitForFunction(
  () =>
    document.documentElement.dataset.theme &&
    !document.querySelector("main").dataset.transition,
);
await page.getByRole("button", { name: /Start exploring/ }).click();
assert.equal(
  await page.locator("main").getAttribute("data-transition"),
  "leaving",
);
assert.equal(await page.locator("main").getAttribute("aria-busy"), "true");
assert.equal(await page.locator("main").evaluate((el) => el.inert), true);
assert.equal(await page.locator(".home-grid").count(), 1);
assert.equal(await page.locator(".observe-grid").count(), 0);
await page.waitForFunction(
  () =>
    Number(
      getComputedStyle(document.querySelector(".home-grid .featured-tile"))
        .opacity,
    ) < 0.75,
);
const exit = await page.locator(".home-grid .image-tile").evaluateAll((cards) =>
  cards.map((el) => ({
    selected: el.classList.contains("primary-tile"),
    opacity: Number(getComputedStyle(el).opacity),
    scale: new DOMMatrix(getComputedStyle(el).transform).a,
  })),
);
const exitHtml = (await page.content()).replace(
  /<script\b[^>]*>[\s\S]*?<\/script>/gi,
  "",
);
await page.getByRole("navigation", { name: "Observe panel" }).waitFor();
await page.waitForFunction(
  () => !document.querySelector("main").dataset.transition,
);
assert.equal(await page.locator("main").evaluate((el) => el.inert), false);
assert.equal(await page.locator("main").getAttribute("aria-busy"), null);
// Turning motion off mid-exit must complete the pending navigation rather than cancel it.
await page.getByRole("link", { name: "Nebo, home" }).click();
await page.waitForFunction(
  () => document.querySelector("main").dataset.transition === "leaving",
);
await page.emulateMedia({ reducedMotion: "reduce" });
await page.getByRole("navigation", { name: "Home panel" }).waitFor();
assert.equal(await page.locator("main").evaluate((el) => el.inert), false);
assert.equal(await page.locator("main").getAttribute("data-transition"), null);
await page.getByRole("button", { name: /Start exploring/ }).click();
await page.getByRole("navigation", { name: "Observe panel" }).waitFor();
assert.equal(await page.locator("main").getAttribute("data-transition"), null);
await page.getByRole("button", { name: /Search by coordinates/ }).click();
await page.getByLabel("Right ascension").waitFor();
await page.getByRole("button", { name: "Back", exact: true }).click();
await page.getByRole("navigation", { name: "Observe panel" }).waitFor();
// Repeated programmatic activation during the real click's exit must not queue navigation.
await page.emulateMedia({ reducedMotion: "no-preference" });
await page.waitForFunction(
  () => !document.querySelector("main").dataset.transition,
);
await page.getByRole("link", { name: "Nebo, home" }).click();
await page.getByRole("navigation", { name: "Home panel" }).waitFor();
await page.waitForFunction(
  () => !document.querySelector("main").dataset.transition,
);
const trigger = page.getByRole("button", { name: /Start exploring/ });
await trigger.click();
await trigger.evaluate((el) => {
  el.click();
  el.click();
});
await page.getByRole("navigation", { name: "Observe panel" }).waitFor();
await page.waitForFunction(
  () => !document.querySelector("main").dataset.transition,
);
assert.ok(
  await page
    .locator(".observe-grid .image-tile")
    .evaluateAll((cards) =>
      cards.every(
        (el) => getComputedStyle(el).opacity === "1" && !el.style.transform,
      ),
    ),
);
// Freeze the actual rendered DOM at the sampled frame so screenshot capture cannot
// race the 300ms transition and accidentally show the following menu.
const still = await browser.newPage({ viewport: { width: 1280, height: 800 } });
await still.goto(process.env.NEBO_TEST_URL || "http://localhost:3002");
await still.setContent(exitHtml);
await still.screenshot({ path: out + "exit-desktop.png", fullPage: true });
await still.close();
assert.deepEqual(errors, []);
writeFileSync(
  out + "navigation-results.json",
  JSON.stringify(
    {
      exit,
      sequentialExit: true,
      busyDuringExit: true,
      reducedMotionDuringExit: true,
      repeatedActivation: true,
      errors,
    },
    null,
    2,
  ),
);
await browser.close();
console.log("Navigation motion passed");
