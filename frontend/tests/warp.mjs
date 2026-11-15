import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
const url = process.env.NEBO_TEST_URL || "http://localhost:3001";
const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome",
  headless: true,
  args: ["--no-sandbox"],
});

const cors = { "Access-Control-Allow-Origin": "*" };
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

// "Begin exploring" opens the sky globe (Aladin). Its map servers are outside this test, so they
// are blocked (Aladin then logs errors, which are expected). The globe is "ready" as soon as
// Aladin has started, and its code is only downloaded when the button is pressed: delaying every
// script requested from then on by `scriptDelayMs` is how a slow globe is simulated, and the
// tunnel must wait for it.
async function run({
  scriptDelayMs = 0,
  reducedMotion = "no-preference",
} = {}) {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 720 },
    reducedMotion,
  });
  const errors = [];
  page.on("pageerror", (e) => {
    if (!/HiPS|Failed to fetch/.test(e.message)) errors.push(e.message);
  });
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({
      json: path.endsWith("/targets") ? targets : [],
      headers: cors,
    });
  });
  await page.route(/alasky\.|irsa\.ipac\.caltech\.edu/, (route) =>
    route.abort(),
  );
  await page.goto(url);
  await page.waitForFunction(() => document.documentElement.dataset.theme);
  await page.getByRole("button", { name: /Start exploring/ }).click();
  await page
    .getByRole("heading", { level: 1, name: "Observe", exact: true })
    .waitFor();
  // Record when the overlay appears and disappears, with the clock of the page.
  await page.evaluate(() => {
    window.__events = [];
    new MutationObserver((muts) => {
      for (const m of muts) {
        for (const n of m.addedNodes)
          if (n.nodeType === 1 && n.matches?.("[data-warp]"))
            window.__events.push(["added", performance.now()]);
        for (const n of m.removedNodes)
          if (n.nodeType === 1 && n.matches?.("[data-warp]"))
            window.__events.push(["removed", performance.now()]);
      }
    }).observe(document.body, { childList: true, subtree: true });
  });
  if (scriptDelayMs) {
    // Installed now, after the menu has loaded its own scripts: only what the globe needs is slow.
    await page.route("**/_next/static/**/*.js", async (route) => {
      await new Promise((r) => setTimeout(r, scriptDelayMs));
      await route.continue();
    });
  }
  const clickedAt = await page.evaluate(() => performance.now());
  await page.getByRole("button", { name: /Begin\s*exploring/ }).click();
  return { page, errors, clickedAt };
}

const events = (page) => page.evaluate(() => window.__events);

// --- 1. the tunnel appears at once, loads the globe behind it and leaves by itself ------------
{
  const { page, errors, clickedAt } = await run();
  const overlay = page.locator("[data-warp]");
  await overlay.waitFor({ timeout: 2000 });
  const [added] = (await events(page)).filter(([k]) => k === "added");
  assert.ok(
    added[1] - clickedAt < 600,
    `appeared ${Math.round(added[1] - clickedAt)} ms after the click`,
  );
  assert.equal(await overlay.locator("canvas").count(), 1);
  assert.equal(await overlay.getAttribute("data-reduced"), "false");
  assert.ok(
    await overlay.getByText("Preparing the images…").isVisible(),
    "the loading text is shown",
  );
  // It covers the whole screen and takes the keyboard focus, so the menu cannot be pressed again.
  const box = await overlay.boundingBox();
  assert.deepEqual([box.width, box.height], [1280, 720]);
  assert.equal(
    await page.evaluate(() =>
      document.activeElement?.hasAttribute("data-warp"),
    ),
    true,
  );

  await overlay.waitFor({ state: "detached", timeout: 20000 });
  const all = await events(page);
  assert.equal(all.filter(([k]) => k === "added").length, 1, "mounted once");
  const [, removedAt] = all.find(([k]) => k === "removed");
  const total = removedAt - added[1];
  // Never a flash (the minimum time), never endless (the safety net is 12 s + the arrival).
  assert.ok(total >= 1900 && total < 8000, `ran ${Math.round(total)} ms`);
  // What is left is the globe, visible, and the keyboard is on its heading.
  await page.locator(".explorer-grid:not([hidden]) .aladin-host").waitFor();
  assert.equal(
    await page.evaluate(() => document.activeElement?.tagName),
    "H1",
    "the keyboard is handed to the screen the user arrived at",
  );
  assert.deepEqual(errors, []);
  await page.close();
}

// --- 2. it stays as the loading screen for as long as the globe takes -------------------------
{
  const { page, clickedAt } = await run({ scriptDelayMs: 4500 });
  const overlay = page.locator("[data-warp]");
  await overlay.waitFor({ timeout: 2000 });
  // Well past the minimum time (1.9 s) but before the globe's code arrives (4.5 s): still in the tunnel.
  await page.waitForTimeout(3000);
  assert.equal(await overlay.count(), 1, "still loading");
  assert.equal(await overlay.evaluate((el) => Number(el.style.opacity)), 1);
  await overlay.waitFor({ state: "detached", timeout: 20000 });
  const [, removedAt] = (await events(page)).find(([k]) => k === "removed");
  assert.ok(removedAt - clickedAt > 4500, "it waited for the globe");
  await page.close();
}

// --- 3. reduced motion: no tunnel, a short dim-and-reveal ------------------------------------
{
  const { page, errors } = await run({ reducedMotion: "reduce" });
  const overlay = page.locator("[data-warp]");
  await overlay.waitFor({ timeout: 2000 });
  assert.equal(await overlay.getAttribute("data-reduced"), "true");
  const [added] = (await events(page)).filter(([k]) => k === "added");
  await overlay.waitFor({ state: "detached", timeout: 20000 });
  const [, removedAt] = (await events(page)).find(([k]) => k === "removed");
  assert.ok(
    removedAt - added[1] < 4000,
    `reduced motion ran ${Math.round(removedAt - added[1])} ms`,
  );
  assert.deepEqual(errors, []);
  await page.close();
}

await browser.close();
console.log("Warp transition passed");
