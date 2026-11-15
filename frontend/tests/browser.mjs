// End-to-end browser check of the real user journey, against a running frontend with the API
// mocked: start screen, tutorial, START -> cockpit, Objects -> View images -> field console
// (including a 202 "building" answer), and Back to the cockpit.
//
//   npm run dev                          # in another terminal (or set NEBO_TEST_URL)
//   node tests/browser.mjs
//
// NEBO_CHROME: path to a Chrome/Chromium binary (default: /usr/bin/google-chrome when it exists,
// else Playwright's own Chromium). NEBO_ARTIFACTS: where screenshots and results go (default: a
// folder in the system temp directory, so a run never dirties the repo).
import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const out = process.env.NEBO_ARTIFACTS || path.join(os.tmpdir(), "nebo-browser");
mkdirSync(out, { recursive: true });
const chrome =
  process.env.NEBO_CHROME || (existsSync("/usr/bin/google-chrome") ? "/usr/bin/google-chrome" : undefined);
const browser = await chromium.launch({
  ...(chrome ? { executablePath: chrome } : {}),
  headless: true,
  args: ["--no-sandbox"],
});
// The app is desktop-only for now.
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

const TUTORIAL = [
  "Start screen",
  "Cockpit",
  "Around the cockpit",
  "Choose a target",
  "Compare epochs",
  "Layers, links and analysis",
  "Read the result",
];
const targets = [
  {
    slug: "barnards-star",
    name: "Barnard's Star",
    ra: 269.446223,
    dec: 4.76878,
    kind: "star",
    note: "Test",
    recommended_detector: 3,
  },
];
const cors = { "Access-Control-Allow-Origin": "*" };
let mode = "ready",
  timelineRequests = 0;
await page.route("**/api/v1/**", async (route) => {
  const url = new URL(route.request().url());
  const p = url.pathname;
  if (p.endsWith("/targets")) return route.fulfill({ json: targets, headers: cors });
  if (p.endsWith("/patches"))
    return route.fulfill({ json: [{ target_slug: "barnards-star", detectors_ready: [3] }], headers: cors });
  if (p.endsWith("/timeline")) {
    timelineRequests++;
    if (mode === "building") {
      mode = "ready";
      return route.fulfill({
        status: 202,
        headers: { ...cors, "Retry-After": "1" },
        json: { status: "building", progress: { stage: "querying", done: 1, total: 2 }, retry_after_s: 1 },
      });
    }
    return route.fulfill({
      headers: cors,
      json: {
        status: "ready",
        patch: { ra: 269.446223, dec: 4.76878, target: "barnards-star" },
        detector: { id: 3, wavelength_range_um: [1.63, 2.41] },
        size: { side_arcmin: 6, pixel_scale_arcsec: 6.15 },
        epochs: Array.from({ length: 3 }, (_, i) => ({
          index: i,
          start_utc: `202${i + 3}-08-15T20:45:11Z`,
          end_utc: `202${i + 3}-08-16T20:45:11Z`,
          frames_used: 8,
          image_url: `/api/v1/images/${i + 1}.png`,
        })),
      },
    });
  }
  if (/\/images\/\d+\.png$/.test(p))
    return route.fulfill({
      status: 200,
      contentType: "image/png",
      headers: cors,
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0ZkAAAAASUVORK5CYII=",
        "base64",
      ),
    });
  // Everything else (chat, Gaia, spectra, models…) is optional for this journey.
  return route.fulfill({ status: 404, headers: cors, json: { detail: "not mocked" } });
});

// localhost, not 127.0.0.1: `next dev` blocks its scripts for other origins and the page never
// hydrates.
await page.goto(process.env.NEBO_TEST_URL || "http://localhost:3000");
await page.evaluate(() => document.fonts.ready);
await page.waitForFunction(() => document.documentElement.dataset.reduced);

// --- start screen ------------------------------------------------------------------------------
const menu = page.getByRole("navigation", { name: "Start menu" });
assert.equal(await menu.getByRole("button").count(), 2, "START and TUTORIAL");
assert.ok(
  await page
    .locator('[data-scene="home"] img')
    .evaluateAll((images) => images.every((img) => img.complete && img.naturalWidth > 0)),
  "start screen art loaded",
);
await page.screenshot({ path: path.join(out, "home.png") });
await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" });
const axe = await page.evaluate(async () => (await window.axe.run()).violations);
writeFileSync(path.join(out, "axe.json"), JSON.stringify(axe, null, 2));
assert.deepEqual(axe.map((v) => v.id), [], "no axe violations on the start screen");

// --- tutorial: every step, buttons and keyboard, and back to the menu --------------------------
const step = (title) => page.getByRole("heading", { level: 2, name: title, exact: true });
await menu.getByRole("button", { name: /Tutorial/ }).click();
await step(TUTORIAL[0]).waitFor();
assert.equal(await page.evaluate(() => document.activeElement?.textContent), TUTORIAL[0], "focus on the step title");
await page.getByRole("button", { name: /^Next/ }).click();
await step(TUTORIAL[1]).waitFor();
await page.keyboard.press("ArrowRight");
await step(TUTORIAL[2]).waitFor();
await page.keyboard.press("ArrowLeft");
await step(TUTORIAL[1]).waitFor();
for (const title of TUTORIAL.slice(2)) {
  await page.getByRole("button", { name: /^Next/ }).click();
  await step(title).waitFor();
}
assert.equal(await page.getByRole("button", { name: /^Launch/ }).count(), 1, "last step offers Launch");
await page.keyboard.press("Escape");
await menu.waitFor();
assert.equal(await page.getByRole("dialog").count(), 0, "tutorial closed");

// --- 200 % text and RTL do not break the start screen at desktop sizes -------------------------
const stress = [];
for (const viewport of [
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
]) {
  await page.setViewportSize(viewport);
  await menu.waitFor();
  for (const [prop, value] of [
    ["fontSize", "200%"],
    ["dir", "rtl"],
  ]) {
    await page.evaluate(([k, v]) => {
      if (k === "dir") document.documentElement.dir = v;
      else document.documentElement.style.fontSize = v;
    }, [prop, value]);
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      `no horizontal scroll at ${viewport.width}x${viewport.height} with ${prop}=${value}`,
    );
  }
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "";
    document.documentElement.dir = "ltr";
  });
  stress.push(viewport);
}

// --- START -> cockpit: locked while the power-on and the approach play, then usable -----------
await menu.getByRole("button", { name: /Start/ }).click();
const objectsTab = page.getByRole("tab", { name: "Objects" });
await objectsTab.waitFor({ timeout: 30_000 });
await page.waitForFunction(() => !document.querySelector("[inert]")?.contains(document.querySelector('[role="tablist"]')), null, {
  timeout: 30_000,
});
await page.screenshot({ path: path.join(out, "cockpit.png") });

// --- Objects -> Barnard's Star -> View images -> field console --------------------------------
await objectsTab.click();
await page.getByRole("tabpanel").getByRole("button", { name: /Barnard's Star/ }).click();
mode = "building"; // the first /timeline answer is 202, the retry is ready
const before = timelineRequests;
await page.getByRole("button", { name: /View images/ }).click();
await page.getByRole("heading", { level: 1, name: "Barnard's Star", exact: true }).waitFor({ timeout: 30_000 });
await page.getByRole("group", { name: "Epochs by date" }).waitFor({ timeout: 30_000 });
assert.ok(timelineRequests - before >= 2, "the field retried after the 202 building answer");
assert.ok(
  await page.waitForFunction(
    () => [...document.querySelectorAll('[data-console="field"] img')].some((i) => i.complete && i.naturalWidth > 0),
    null,
    { timeout: 30_000 },
  ),
  "an epoch image is shown",
);
await page.screenshot({ path: path.join(out, "field.png") });

// --- Back to the cockpit -----------------------------------------------------------------------
await page.locator('[data-console="field"]').getByRole("button", { name: "Back", exact: true }).click();
await objectsTab.waitFor({ timeout: 30_000 });

assert.deepEqual(errors, [], "no uncaught page errors");
writeFileSync(
  path.join(out, "browser-results.json"),
  JSON.stringify(
    {
      passed: true,
      timelineRequests,
      errors,
      stress,
      checks: [
        "start screen: menu, art, axe",
        "tutorial: 7 steps, buttons, keyboard, back to the menu",
        "200% text and RTL at desktop sizes",
        "START -> cockpit unlocked",
        "Objects -> View images -> field (202 then ready, epoch image)",
        "Back to the cockpit",
      ],
    },
    null,
    2,
  ),
);
await browser.close();
console.log(`Browser flows passed (results in ${out})`);
