import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const out = new URL("../../../artifacts/nebo/", import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox"],
});
const page = await browser.newPage({
  viewport: { width: 375, height: 812 },
  reducedMotion: "reduce",
});
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
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
let mode = "ready",
  requests = 0;
await page.route("**/api/v1/**", async (route) => {
  const url = new URL(route.request().url());
  let body;
  if (url.pathname.endsWith("/targets")) body = targets;
  else if (url.pathname.endsWith("/patches"))
    body = [{ target_slug: "barnards-star", detectors_ready: [3] }];
  else if (url.pathname.endsWith("/timeline")) {
    requests++;
    if (mode === "building") {
      mode = "ready";
      await route.fulfill({
        status: 202,
        headers: { "Access-Control-Allow-Origin": "*", "Retry-After": "1" },
        json: {
          status: "building",
          progress: { stage: "querying", done: 1, total: 2 },
          retry_after_s: 1,
        },
      });
      return;
    }
    if (mode === "error") {
      await route.fulfill({
        status: 503,
        headers: { "Access-Control-Allow-Origin": "*" },
        json: { code: "database_not_configured" },
      });
      return;
    }
    body = {
      status: "ready",
      patch: { ra: 269.446223, dec: 4.76878 },
      detector: { id: 3, wavelength_range_um: [1.63, 2.41] },
      size: { side_arcmin: 6, pixel_scale_arcsec: 6.15 },
      epochs:
        mode === "empty"
          ? []
          : Array.from({ length: mode === "single" ? 1 : 3 }, (_, i) => ({
              index: i,
              start_utc: `202${i + 3}-08-15T20:45:11Z`,
              end_utc: `202${i + 3}-08-16T20:45:11Z`,
              frames_used: 8,
              image_url: "/api/v1/images/" + (i + 1) + ".png",
            })),
    };
  } else if (url.pathname.includes("/images/")) {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: Buffer.from(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0ZkAAAAASUVORK5CYII=",
        "base64",
      ),
      headers: { "Access-Control-Allow-Origin": "*" },
    });
    return;
  }
  await route.fulfill({
    json: body,
    headers: { "Access-Control-Allow-Origin": "*" },
  });
});
await page.goto(process.env.NEBO_TEST_URL || "http://127.0.0.1:3001");
// The field console uses its own listbox (styled like the ship), not a native <select>.
await page.evaluate(() => document.fonts.ready);
await page.waitForFunction(() => document.documentElement.dataset.reduced);
assert.equal(await page.locator(".nav").count(), 0);
// The start screen is the ship on the ground: START and TUTORIAL on its wall screen.
assert.equal(
  await page.getByRole("navigation", { name: "Start menu" }).getByRole("button").count(),
  2,
);
assert.equal(
  await page.getByText("YOUR WINDOW TO THE UNIVERSE", { exact: true }).count(),
  0,
);
assert.equal(await page.getByText("The sky has", { exact: false }).count(), 0);
assert.ok(
  await page
    .locator('[data-scene="home"] img')
    .evaluateAll((images) =>
      images.every((img) => img.complete && img.naturalWidth > 0),
    ),
);
await page.screenshot({ path: out + "home-mobile.png", fullPage: true });
await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" });
const axe = await page.evaluate(async () => {
  const r = await window.axe.run();
  return r.violations;
});
writeFileSync(out + "axe.json", JSON.stringify(axe, null, 2));
assert.deepEqual(
  axe.map((v) => v.id),
  [],
);
// The tutorial runs on the same wall screen: four steps, Back/Next, keyboard, and back to the menu.
await page
  .getByRole("navigation", { name: "Start menu" })
  .getByRole("button", { name: /Tutorial/ })
  .click();
await page.getByRole("heading", { level: 2, name: "Launch", exact: true }).waitFor();
assert.equal(
  await page.evaluate(() => document.activeElement?.textContent),
  "Launch",
  "focus moves to the step title",
);
await page.getByRole("button", { name: /^Next/ }).click();
await page.getByRole("heading", { level: 2, name: "Fly", exact: true }).waitFor();
await page.keyboard.press("ArrowRight");
await page.getByRole("heading", { level: 2, name: "Observe", exact: true }).waitFor();
await page.keyboard.press("ArrowLeft");
await page.getByRole("heading", { level: 2, name: "Fly", exact: true }).waitFor();
await page.getByRole("button", { name: /^Next/ }).click();
await page.getByRole("button", { name: /^Next/ }).click();
await page.getByRole("heading", { level: 2, name: "Compare", exact: true }).waitFor();
assert.equal(await page.getByRole("button", { name: /^Launch/ }).count(), 1);
await page.keyboard.press("Escape");
await page.getByRole("navigation", { name: "Start menu" }).waitFor();
const stress = [];
for (const viewport of [
  { width: 320, height: 568 },
  { width: 568, height: 320 },
  { width: 375, height: 812 },
]) {
  await page.setViewportSize(viewport);
  // Already on the start screen, which has no site header (and so no home link).
  await page.getByRole("navigation", { name: "Start menu" }).waitFor();
  await page.evaluate(() => (document.documentElement.style.fontSize = "200%"));
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
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
  stress.push(viewport);
}
await page.setViewportSize({ width: 1280, height: 800 });
await page.screenshot({ path: out + "home-desktop.png", fullPage: true });
assert.deepEqual(errors, []);
writeFileSync(
  out + "browser-results.json",
  JSON.stringify(
    {
      passed: true,
      requests,
      errors,
      stress,
      checks: [
        "tutorial: steps, keyboard, back to the menu",
        "200% text",
        "RTL",
      ],
    },
    null,
    2,
  ),
);
await browser.close();
console.log("Browser flows passed");
