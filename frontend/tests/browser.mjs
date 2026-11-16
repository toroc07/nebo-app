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
  timelineRequests = 0,
  gaiaRequests = 0,
  lastTimelineQuery = "";
const epochsOf = (n, frames) =>
  Array.from({ length: n }, (_, i) => ({
    index: i,
    start_utc: `202${i + 3}-08-15T20:45:11Z`,
    end_utc: `202${i + 3}-08-16T20:45:11Z`,
    mid_mjd: 60000 + 180 * i,
    frames_used: frames,
    image_url: `/api/v1/images/${i + 1}.png`,
  }));
await page.route("**/api/v1/**", async (route) => {
  const url = new URL(route.request().url());
  const p = url.pathname;
  if (p.endsWith("/targets")) return route.fulfill({ json: targets, headers: cors });
  if (p.endsWith("/patches"))
    return route.fulfill({ json: [{ target_slug: "barnards-star", detectors_ready: [3] }], headers: cors });
  if (p.endsWith("/timeline")) {
    timelineRequests++;
    lastTimelineQuery = url.search;
    // A progressive build at `preview_ready`: every epoch already has its one-frame preview.
    if (mode === "preview")
      return route.fulfill({
        status: 202,
        headers: { ...cors, "Retry-After": "1" },
        json: {
          status: "building",
          patch: { id: 7, ra: 269.446223, dec: 4.76878, target: "barnards-star" },
          detector: { id: 3, wavelength_range_um: [1.63, 2.41] },
          size: { side_arcmin: 6, pixel_scale_arcsec: 6.15 },
          is_partial: true,
          progress: { stage: "preview_ready", done: 3, total: 24 },
          retry_after_s: 1,
          epochs: epochsOf(3, 1),
        },
      });
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
        patch: { id: 7, ra: 269.446223, dec: 4.76878, target: "barnards-star" },
        detector: { id: 3, wavelength_range_um: [1.63, 2.41] },
        size: { side_arcmin: 6, pixel_scale_arcsec: 6.15 },
        epochs: epochsOf(3, 8),
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
  if (/\/patches\/\d+\/gaia$/.test(p)) {
    gaiaRequests++;
    const mjds = url.searchParams.getAll("mjd").map(Number);
    return route.fulfill({
      headers: cors,
      json: {
        patch_id: 7,
        size: { name: "medium", width_px: 1, height_px: 1 },
        catalog: { name: "Gaia DR3", ref_epoch: 2016, g_max: 18, g_complete: 18, radius_deg: 0.1, truncated: false, note: "" },
        mjd: mjds,
        stars: [
          {
            source_id: "1",
            g_mag: 9.5,
            bp_rp: 2.8,
            pm_ra_mas_yr: 0,
            pm_dec_mas_yr: 0,
            pm_total_mas_yr: 0,
            parallax_mas: 1,
            distance_pc: 1000,
            positions: mjds.map((mjd) => ({ mjd, ra: 269.446223, dec: 4.76878, x: 0, y: 0, in_image: true })),
          },
        ],
      },
    });
  }
  // Everything else (chat, CatWISE, spectra, models…) is optional for this journey.
  return route.fulfill({ status: 404, headers: cors, json: { detail: "not mocked" } });
});

// localhost, not 127.0.0.1: `next dev` blocks its scripts for other origins and the page never
// hydrates.
await page.goto(process.env.NEBO_TEST_URL || "http://localhost:3000");
await page.evaluate(() => document.fonts.ready);
await page.waitForFunction(() => document.documentElement.dataset.reduced);

// --- start screen ------------------------------------------------------------------------------
const menu = page.getByRole("navigation", { name: "Start menu" });
assert.equal(await menu.getByRole("button").count(), 3, "START, TUTORIAL and CREW");
assert.equal(
  await page.getByRole("link", { name: /Nebo source code on GitHub/ }).getAttribute("href"),
  "https://github.com/toroc07/nebo-app",
  "the start screen links to the repository",
);
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

// --- crew: the team panel replaces the menu, and Back returns to it ----------------------------
await menu.getByRole("button", { name: /Crew/ }).click();
await page.getByRole("heading", { level: 2, name: "Crew", exact: true }).waitFor();
assert.equal(await page.locator("section[aria-labelledby='crew-title'] li").count(), 6, "six crew members");
await page.getByText("Universidad Tecnológica de Bolívar").waitFor();
assert.equal(await page.locator("section[aria-labelledby='crew-title'] a[href^='https://github.com/']").count(), 6, "six GitHub links");
assert.equal(
  await page.getByRole("link", { name: /Jasen .* on GitHub/ }).getAttribute("href"),
  "https://github.com/Jmyukopila",
);
await page.getByRole("button", { name: "Back", exact: true }).click();
await menu.getByRole("button", { name: /Tutorial/ }).waitFor();

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
// The map flies to the selection, so its marker sits at the map centre: hovering it names it.
{
  const box = await page.getByRole("region", { name: /SPHEREx sky map/ }).boundingBox();
  const label = page.locator(".sky-label").filter({ hasText: "Barnard's Star" });
  for (let i = 0; i < 20 && !(await label.count()); i++) {
    await page.mouse.move(box.x + box.width / 2 + (i % 2), box.y + box.height / 2);
    await page.waitForTimeout(250);
  }
  await label.waitFor({ timeout: 5_000 });
  await page.mouse.move(box.x + 10, box.y + 10);
  await label.waitFor({ state: "detached", timeout: 5_000 });
}
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

// --- A field still building: its preview can be blinked and Gaia works before it is done --------
mode = "preview";
gaiaRequests = 0;
await objectsTab.click();
await page.getByRole("tabpanel").getByRole("button", { name: /Barnard's Star/ }).click();
await page.getByRole("button", { name: /View images/ }).click();
const field = page.locator('[data-console="field"]');
await page.waitForFunction(
  () => {
    const b = [...document.querySelectorAll("button")].find((e) => e.textContent?.trim() === "Compare preview");
    return b && !b.disabled;
  },
  null,
  { timeout: 30_000 },
);
assert.ok(await field.getByRole("button", { name: "Next epoch" }).isEnabled(), "epochs can be stepped in the preview");
assert.ok(await field.getByRole("button", { name: "Stack", exact: true }).isDisabled(), "the stack waits for the final images");
const layerGroup = field.getByRole("group", { name: "Catalog layers" });
assert.ok(await layerGroup.getByRole("button", { name: "Changes", exact: true }).isDisabled(), "changes need the final images");
for (let i = 0; i < 50 && gaiaRequests === 0; i++) await page.waitForTimeout(100);
assert.ok(gaiaRequests > 0, "Gaia is prefetched while the field builds, before the layer is switched on");
const prefetched = gaiaRequests;
await layerGroup.getByRole("button", { name: "Gaia DR3", exact: true }).click();
await page.locator("#layer-status").filter({ hasText: /Gaia: 1 stars? on this image/ }).waitFor({ timeout: 10_000 });
assert.equal(gaiaRequests, prefetched, "switching the prefetched layer on does not ask again");
await page.screenshot({ path: path.join(out, "field-building.png") });
mode = "ready";
await field.getByRole("button", { name: "Compare epochs" }).waitFor({ timeout: 30_000 });
// The final timeline keeps the patch and the epoch dates: the catalogue layer stays, not reloaded.
await page.locator("#layer-status").filter({ hasText: /Gaia: 1 stars? on this image/ }).waitFor({ timeout: 10_000 });
assert.equal(gaiaRequests, prefetched, "the final images do not reload the catalogue layer");
await page.screenshot({ path: path.join(out, "field-final.png") });
await field.getByRole("button", { name: "Back", exact: true }).click();
await objectsTab.waitFor({ timeout: 30_000 });

// --- Dragging the selected object off the centre reticle forgets it -----------------------------
// Back from the field, Barnard's Star is still selected and centred: View images would reopen it.
// Dragging the map away must drop it, so View images opens the new map centre instead.
const map = page.getByRole("region", { name: /SPHEREx sky map/ });
const box = await map.boundingBox();
const cx = box.x + box.width / 2,
  cy = box.y + box.height / 3;
// The return warp covers the map for a moment: drag once the map itself is under the pointer.
await page.waitForFunction(
  ([x, y]) => !!document.elementFromPoint(x, y)?.closest(".aladin-host"),
  [cx, cy],
  { timeout: 15_000 },
);
await page.mouse.move(cx, cy);
await page.mouse.down();
// A hand-paced drag: Aladin's WASM throws "recursive use of an object" when pointer moves arrive
// faster than it draws (it happens without Nebo's code too, in the headless browser).
for (let i = 1; i <= 10; i++) {
  await page.mouse.move(cx + 30 * i, cy + 12 * i);
  await page.waitForTimeout(60);
}
await page.mouse.up();
await page.waitForTimeout(500);
await page.getByRole("button", { name: /View images/ }).click();
await field.getByRole("button", { name: "Back", exact: true }).waitFor({ timeout: 30_000 });
for (let i = 0; i < 50 && !/[?&]ra=/.test(lastTimelineQuery); i++) await page.waitForTimeout(100);
assert.match(lastTimelineQuery, /[?&]ra=/, "after dragging away, View images opens the map centre, not the old object");
assert.doesNotMatch(lastTimelineQuery, /target=barnards-star/);
await field.getByRole("button", { name: "Back", exact: true }).click();
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
        "crew panel and back",
        "tutorial: 7 steps, buttons, keyboard, back to the menu",
        "200% text and RTL at desktop sizes",
        "START -> cockpit unlocked",
        "Hovering a sky-map marker names it above the pointer",
        "Objects -> View images -> field (202 then ready, epoch image)",
        "Back to the cockpit",
        "Field at preview_ready: compare and step enabled, stack and changes wait, Gaia prefetched once",
        "Dragging the selected object off-centre deselects it: View images opens the map centre",
      ],
    },
    null,
    2,
  ),
);
await browser.close();
console.log(`Browser flows passed (results in ${out})`);
