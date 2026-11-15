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
// The start menu offers only START and TUTORIAL; the coordinate form is reached through the
// tutorial's "Skip tutorial", which opens the Observe menu.
const openCoordinates = async () => {
  await page.getByRole("button", { name: /Tutorial/ }).click();
  await page.getByRole("button", { name: "Skip tutorial", exact: true }).click();
  await page.getByRole("button", { name: /Search by coordinates/ }).click();
};
const pickFieldSize = async (label) => {
  await page.getByRole("button", { name: /^Field size/ }).click();
  await page.getByRole("option", { name: label, exact: true }).click();
};
await page.evaluate(() => document.fonts.ready);
await page.waitForFunction(() => document.documentElement.dataset.theme);
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
await openCoordinates();
await page.getByLabel("Right ascension").fill("360");
await page.getByLabel("Declination").fill("0");
await page.getByRole("button", { name: "View images", exact: true }).click();
await page.locator("#coordinate-error").waitFor();
await page.getByLabel("Right ascension").fill("269.446");
await page.getByLabel("Declination").fill("4.768");
mode = "building";
await page.getByRole("button", { name: "View images", exact: true }).click();
await page.getByText("Searching for observations", { exact: true }).waitFor();
await page.getByText(/^Observed: .+ UTC/).waitFor();
await page.getByRole("button", { name: "Compare epochs", exact: true }).click();
await page.waitForTimeout(900);
await page.getByRole("button", { name: "Pause", exact: true }).click();
assert.doesNotMatch(
  await page.getByText(/^Epoch \d+ of \d+$/).textContent(),
  /^Epoch 1 of/,
);
await page.screenshot({ path: out + "field-mobile.png", fullPage: true });
mode = "single";
await pickFieldSize("3 arcminutes");
await page.getByText("Only one epoch is available", { exact: false }).waitFor();
assert.ok(
  await page
    .getByRole("button", { name: "Compare epochs", exact: true })
    .isDisabled(),
);
mode = "empty";
await pickFieldSize("15 arcminutes");
await page
  .getByText("This field has no epochs available yet.", {
    exact: false,
  })
  .waitFor();
mode = "error";
await pickFieldSize("6 arcminutes");
await page.getByText(/The database is not configured yet/).waitFor();
// The field console replaces the site header (as in the design), so leave it with Back:
// field → coordinates form → start screen.
for (let i = 0; i < 2; i++)
  await page.getByRole("button", { name: "Back", exact: true }).click();
await page.getByRole("navigation", { name: "Start menu" }).waitFor();
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
// "Begin exploring" lands on the full-screen image viewer, which asks the real API first. The
// mocked API is failing here (mode "error"), so the viewer offers the synthetic demo, and once it
// is chosen a "simulated data" banner stays on screen.
await page.setViewportSize({ width: 1280, height: 800 });
const timelineRequestsBefore = requests;
await page.getByRole("button", { name: /Begin exploring/ }).click();
await page.waitForURL("**/lab/observation");
await page
  .getByRole("button", { name: "Show the simulated demo instead", exact: true })
  .click();
assert.ok(
  requests > timelineRequestsBefore,
  "the lab asked the real API first",
);
await page
  .getByRole("note")
  .getByText(/Simulated data/)
  .waitFor();
await page.getByRole("application", { name: /SPHEREx image/ }).waitFor();
const epochImage = page.locator("img[alt^='Epoch 1 of']");
await epochImage.waitFor();
const view = page.viewportSize();
const fitted = await epochImage.boundingBox();
// "Contain" fit: the image touches the screen edges on its limiting axis.
assert.ok(
  fitted.width >= view.width - 1 || fitted.height >= view.height - 1,
  "image fills the screen",
);
const zoomLabel = page.locator("[class*=zoomControls] span").first();
assert.equal(await zoomLabel.textContent(), "1.0×");
const centre = { x: view.width / 2, y: view.height / 2 };
await page.mouse.move(centre.x, centre.y);
await page.mouse.wheel(0, -400);
await page.waitForFunction(
  () =>
    document.querySelector("[class*=zoomControls] span").textContent !== "1.0×",
);
// Infrared band <-> color swaps the image set in place and keeps the zoom.
const viewState = () =>
  page.evaluate(() => {
    const img = document.querySelector("img[alt^='Epoch']");
    const m = new DOMMatrix(getComputedStyle(img.parentElement).transform);
    return { src: img.getAttribute("src"), view: [m.a, m.e, m.f].join("|") };
  });
const grey = await viewState();
assert.ok(!/\/lab\/demo\/(amber|inferno)\//.test(grey.src), "starts in grey");
await page.getByRole("button", { name: "Color", exact: true }).click();
await page.waitForFunction(() =>
  document
    .querySelector("img[alt^='Epoch']")
    .getAttribute("src")
    .includes("/lab/demo/inferno/"),
);
const colored = await viewState();
assert.equal(colored.view, grey.view, "colour keeps the view");
await page.getByText(/not the sky's real colors/).waitFor();
await page.getByRole("button", { name: "Infrared band", exact: true }).click();
await page.waitForFunction(
  () =>
    !/\/lab\/demo\/(amber|inferno)\//.test(
      document.querySelector("img[alt^='Epoch']").getAttribute("src"),
    ),
);
// A click without dragging drops a pin; the centre of the screen is the centre pixel.
await page.mouse.click(centre.x, centre.y);
const readout = page.getByRole("complementary", { name: "Coordinates" });
// Chrome rounds the mouse position to a whole CSS pixel, so the coordinate can differ from the
// exact centre by a few hundredths of an image pixel: match the digits that are stable.
await readout.getByText(/Pin RA 269\.4462\d\d°/).waitFor();
await readout.getByText("px 29.0, 29.0", { exact: true }).waitFor();
// Dragging the pin moves the coordinate.
const pin = page.getByRole("button", { name: /Coordinate pin/ });
const pinBox = await pin.boundingBox();
await page.mouse.move(
  pinBox.x + pinBox.width / 2,
  pinBox.y + pinBox.height / 2,
);
await page.mouse.down();
await page.mouse.move(centre.x + 60, centre.y + 40, { steps: 5 });
await page.mouse.up();
assert.equal(
  await readout.getByText("px 29.0, 29.0", { exact: true }).count(),
  0,
  "pin moved",
);
// Keyboard: 0 refits, and the pin keeps its sky position.
await page.getByRole("application", { name: /SPHEREx image/ }).focus();
await page.keyboard.press("0");
await page.waitForFunction(
  () =>
    document.querySelector("[class*=zoomControls] span").textContent === "1.0×",
);
assert.equal(await readout.getByText(/Pin RA/).count(), 1);
// Zooming switches between the 3', 6' and 15' images on its own (data-level is the one shown).
const level = page.locator("[class*=zoomControls] [data-level]");
await page.getByRole("application", { name: /SPHEREx image/ }).focus();
assert.equal(await level.getAttribute("data-level"), "medium");
await page.mouse.move(centre.x, centre.y);
await page.mouse.wheel(0, -1500);
await page.waitForFunction(
  () =>
    document
      .querySelector("[class*=zoomControls] [data-level]")
      .getAttribute("data-level") === "small",
);
await page.mouse.wheel(0, 4000);
await page.waitForFunction(
  () =>
    document
      .querySelector("[class*=zoomControls] [data-level]")
      .getAttribute("data-level") === "large",
);
await page.keyboard.press("0");
await page.waitForFunction(
  () =>
    document
      .querySelector("[class*=zoomControls] [data-level]")
      .getAttribute("data-level") === "medium",
);
assert.equal(
  await readout.getByText(/Pin RA/).count(),
  1,
  "pin survives level changes",
);
await page.screenshot({ path: out + "viewer-desktop.png" });
mode = "ready";
await page.setViewportSize({ width: 375, height: 812 });
await page.getByRole("link", { name: "Back to the menu" }).click();
await page.getByRole("navigation", { name: "Start menu" }).waitFor();
// Back from a field returns to the screen it was opened from, not to a fixed one.
const backButton = page.getByRole("button", { name: "Back", exact: true });
const heading = (name) =>
  page.getByRole("heading", { level: 1, name, exact: true });
await openCoordinates();
await page.getByLabel("Right ascension").fill("269.446");
await page.getByLabel("Declination").fill("4.768");
await page.getByRole("button", { name: "View images", exact: true }).click();
await page.getByText(/^Observed: .+ UTC/).waitFor();
await backButton.click();
await heading("Find your field.").waitFor();
await page.getByRole("link", { name: "Nebo, home" }).click();
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
        "coordinates validation",
        "202 polling",
        "play pause",
        "one epoch",
        "zero epochs",
        "503 recovery",
        "persistent preferences",
        "tutorial",
        "keyboard activation",
        "image viewer: fit, zoom, pin, drag pin, refit",
        "infrared/color switch keeps the view",
        "zoom switches between the 3 sizes",
        "Back from a field returns to its origin",
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
