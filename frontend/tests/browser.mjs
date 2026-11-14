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
await page.evaluate(() => document.fonts.ready);
await page.waitForFunction(() => document.documentElement.dataset.theme);
assert.equal(await page.locator(".nav").count(), 0);
assert.equal(
  await page
    .locator(".home-grid > button, .home-grid .secondary-stack > button")
    .count(),
  4,
);
assert.equal(
  await page.getByText("YOUR WINDOW TO THE UNIVERSE", { exact: true }).count(),
  0,
);
assert.equal(await page.getByText("The sky has", { exact: false }).count(), 0);
assert.ok(
  await page
    .locator(".panel-image")
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
await page.getByRole("link", { name: "Nebo, home" }).click();
await page.getByRole("button", { name: /Start exploring/ }).click();
await page.getByRole("button", { name: /Search by coordinates/ }).click();
await page.getByLabel("Right ascension").fill("360");
await page.getByLabel("Declination").fill("0");
await page.getByRole("button", { name: "View images", exact: true }).click();
await page.locator("#coordinate-error").waitFor();
await page.getByLabel("Right ascension").fill("269.446");
await page.getByLabel("Declination").fill("4.768");
mode = "building";
await page.getByRole("button", { name: "View images", exact: true }).click();
await page.getByText("Searching for observations", { exact: true }).waitFor();
await page.getByLabel("Observation date").waitFor();
await page.getByRole("button", { name: "Compare epochs", exact: true }).click();
await page.waitForTimeout(900);
await page.getByRole("button", { name: "Pause", exact: true }).click();
assert.notEqual(await page.locator("#epoch").inputValue(), "0");
await page.screenshot({ path: out + "field-mobile.png", fullPage: true });
mode = "single";
await page.getByLabel("Field size").selectOption("small");
await page.getByText("Only one epoch is available", { exact: false }).waitFor();
assert.ok(
  await page
    .getByRole("button", { name: "Compare epochs", exact: true })
    .isDisabled(),
);
mode = "empty";
await page.getByLabel("Field size").selectOption("large");
await page
  .getByText("This field has no epochs available yet.", {
    exact: false,
  })
  .waitFor();
mode = "error";
await page.getByLabel("Field size").selectOption("medium");
await page.getByText(/The database is not configured yet/).waitFor();
await page.getByRole("link", { name: "Nebo, home" }).click();
await page.getByRole("button", { name: /Settings/ }).click();
await page.getByLabel("Appearance").selectOption("light");
await page.getByLabel("Reduce motion", { exact: true }).check();
await page.reload();
await page.getByRole("link", { name: "Nebo, home" }).click();
await page.getByRole("button", { name: /Settings/ }).click();
assert.equal(await page.getByLabel("Appearance").inputValue(), "light");
assert.ok(await page.getByLabel("Reduce motion", { exact: true }).isChecked());
await page.getByRole("link", { name: "Nebo, home" }).click();
await page.getByRole("button", { name: /Tutorial/ }).click();
await page.getByRole("button", { name: "Next", exact: true }).click();
await page.getByRole("button", { name: "Next", exact: true }).click();
await page.getByRole("button", { name: "Start", exact: true }).click();
// The three main tasks remain keyboard accessible; activate the coordinate tile through Enter.
await page.getByRole("button", { name: /Search by coordinates/ }).focus();
await page.keyboard.press("Enter");
await page.keyboard.press("Tab");
assert.equal(
  await page.evaluate(() => document.activeElement?.id === "ra"),
  true,
);
await page.getByRole("link", { name: "Nebo, home" }).click();
await page.getByRole("button", { name: /Start exploring/ }).click();
await page.screenshot({ path: out + "observe-mobile.png", fullPage: true });
await page.getByRole("button", { name: /Begin exploring/ }).click();
await page.getByRole("button", { name: /Barnard/ }).click();
await page.getByRole("button", { name: "View images", exact: true }).click();
mode = "ready";
await page.getByRole("link", { name: "Nebo, home" }).click();
const stress = [];
for (const viewport of [
  { width: 320, height: 568 },
  { width: 568, height: 320 },
  { width: 375, height: 812 },
]) {
  await page.setViewportSize(viewport);
  await page.getByRole("link", { name: "Nebo, home" }).click();
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
        "coordinates validation",
        "202 polling",
        "play pause",
        "one epoch",
        "zero epochs",
        "503 recovery",
        "persistent preferences",
        "tutorial",
        "keyboard activation",
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
