import { test } from "node:test";
import assert from "node:assert/strict";
import {
  validCoordinates,
  nextEpoch,
  epochDateRange,
  releaseLabel,
  timeline,
  ApiError,
  diffImageUrl,
  rgbImageUrl,
} from "../lib/api";
test("epoch dates show the whole span of the epoch, in UTC", () => {
  assert.equal(
    epochDateRange("2025-08-15T20:45:11+00:00", "2025-08-15T23:59:00+00:00"),
    "Aug 15, 2025",
  );
  assert.equal(
    epochDateRange("2026-03-19T07:25:17+00:00", "2026-05-05T01:59:28+00:00"),
    "Mar 19 – May 5, 2026",
  );
  assert.equal(
    epochDateRange("2025-12-28T10:00:00+00:00", "2026-01-03T10:00:00+00:00"),
    "Dec 28, 2025 – Jan 3, 2026",
  );
  // Late on Aug 15 in UTC is still Aug 15, whatever the viewer's time zone.
  assert.equal(epochDateRange("2025-08-15T23:30:00+00:00"), "Aug 15, 2025");
  assert.equal(epochDateRange("not a date"), "");
});
test("release label comes from the data, never hard-coded", () => {
  assert.equal(releaseLabel(["qr3", "dr1", "dr1"]), "SPHEREx DR1 + QR3");
  assert.equal(releaseLabel(["dr1"]), "SPHEREx DR1");
  assert.equal(releaseLabel([]), "SPHEREx");
  assert.equal(releaseLabel(undefined), "SPHEREx");
});
test("coordinates accept poles and reject blanks, infinities and out of range", () => {
  for (const [ra, dec] of [
    ["0", "-90"],
    ["359.999", "90"],
    ["269.446", "4.768"],
  ])
    assert.ok(validCoordinates(ra, dec));
  for (const [ra, dec] of [
    ["", "0"],
    ["0", ""],
    ["360", "0"],
    ["-1", "0"],
    ["0", "91"],
    ["Infinity", "0"],
    ["x", "0"],
  ])
    assert.equal(validCoordinates(ra, dec), false);
});
test("playback wraps and handles one or zero epochs", () => {
  assert.equal(nextEpoch(2, 3), 0);
  assert.equal(nextEpoch(0, 3), 1);
  assert.equal(nextEpoch(0, 1), 0);
  assert.equal(nextEpoch(0, 0), 0);
});
test("timeline follows 202 progress and returns ready data", async () => {
  const previous = global.fetch;
  let calls = 0;
  global.fetch = async () =>
    new Response(
      JSON.stringify(
        ++calls === 1
          ? {
              status: "building",
              progress: { stage: "querying", done: 0, total: 0 },
              retry_after_s: 1,
            }
          : { status: "ready", epochs: [] },
      ),
      { status: calls === 1 ? 202 : 200, headers: { "Retry-After": "1" } },
    );
  try {
    let progress = false;
    const result = await timeline(
      { ra: 0, dec: 0 },
      "medium",
      3,
      new AbortController().signal,
      () => {
        progress = true;
      },
    );
    assert.equal(result.status, "ready");
    assert.ok(progress);
    assert.equal(calls, 2);
  } finally {
    global.fetch = previous;
  }
});
test("diffImageUrl and rgbImageUrl support both target and ra/dec queries", () => {
  const diffUrl = new URL(
    diffImageUrl({ target: "barnards-star" }, { a: 0, b: 1, detector: 3, size: "medium" }),
  );
  assert.equal(diffUrl.pathname, "/api/v1/timeline/diff");
  assert.equal(diffUrl.searchParams.get("target"), "barnards-star");
  assert.equal(diffUrl.searchParams.get("a"), "0");
  assert.equal(diffUrl.searchParams.get("b"), "1");

  const rgbUrl = new URL(
    rgbImageUrl({ ra: 10.5, dec: -20.25 }, { r: 6, g: 3, b: 1, epoch: 0, size: "large" }),
  );
  assert.equal(rgbUrl.pathname, "/api/v1/timeline/rgb");
  assert.equal(rgbUrl.searchParams.get("ra"), "10.5");
  assert.equal(rgbUrl.searchParams.get("dec"), "-20.25");
  assert.equal(rgbUrl.searchParams.get("r"), "6");
  assert.equal(rgbUrl.searchParams.get("g"), "3");
  assert.equal(rgbUrl.searchParams.get("b"), "1");
});
test("cancelling a build stops polling", async () => {
  const previous = global.fetch;
  let calls = 0;
  global.fetch = async () => {
    calls++;
    return new Response(
      JSON.stringify({
        status: "building",
        progress: { stage: "queued", done: 0, total: 0 },
      }),
      { status: 202 },
    );
  };
  try {
    const controller = new AbortController();
    await assert.rejects(
      timeline({ target: "test" }, "medium", 3, controller.signal, () =>
        setTimeout(() => controller.abort(), 10),
      ),
      { name: "AbortError" },
    );
    assert.equal(calls, 1);
  } finally {
    global.fetch = previous;
  }
});
test("diffImageUrl and rgbImageUrl support both target and ra/dec queries", () => {
  const diffUrl = new URL(
    diffImageUrl({ target: "barnards-star" }, { a: 0, b: 1, detector: 3, size: "medium" }),
  );
  assert.equal(diffUrl.pathname, "/api/v1/timeline/diff");
  assert.equal(diffUrl.searchParams.get("target"), "barnards-star");
  assert.equal(diffUrl.searchParams.get("a"), "0");
  assert.equal(diffUrl.searchParams.get("b"), "1");

  const rgbUrl = new URL(
    rgbImageUrl({ ra: 10.5, dec: -20.25 }, { r: 6, g: 3, b: 1, epoch: 0, size: "large" }),
  );
  assert.equal(rgbUrl.pathname, "/api/v1/timeline/rgb");
  assert.equal(rgbUrl.searchParams.get("ra"), "10.5");
  assert.equal(rgbUrl.searchParams.get("dec"), "-20.25");
  assert.equal(rgbUrl.searchParams.get("r"), "6");
  assert.equal(rgbUrl.searchParams.get("g"), "3");
  assert.equal(rgbUrl.searchParams.get("b"), "1");
});
test("503 database error is actionable", async () => {
  const previous = global.fetch;
  global.fetch = async () =>
    new Response(JSON.stringify({ code: "database_not_configured" }), {
      status: 503,
    });
  try {
    await assert.rejects(
      timeline(
        { ra: 0, dec: 0 },
        "small",
        6,
        new AbortController().signal,
        () => {},
      ),
      (e: unknown) => e instanceof ApiError && e.message.includes("PostgreSQL"),
    );
  } finally {
    global.fetch = previous;
  }
});
test("diffImageUrl and rgbImageUrl support both target and ra/dec queries", () => {
  const diffUrl = new URL(
    diffImageUrl({ target: "barnards-star" }, { a: 0, b: 1, detector: 3, size: "medium" }),
  );
  assert.equal(diffUrl.pathname, "/api/v1/timeline/diff");
  assert.equal(diffUrl.searchParams.get("target"), "barnards-star");
  assert.equal(diffUrl.searchParams.get("a"), "0");
  assert.equal(diffUrl.searchParams.get("b"), "1");

  const rgbUrl = new URL(
    rgbImageUrl({ ra: 10.5, dec: -20.25 }, { r: 6, g: 3, b: 1, epoch: 0, size: "large" }),
  );
  assert.equal(rgbUrl.pathname, "/api/v1/timeline/rgb");
  assert.equal(rgbUrl.searchParams.get("ra"), "10.5");
  assert.equal(rgbUrl.searchParams.get("dec"), "-20.25");
  assert.equal(rgbUrl.searchParams.get("r"), "6");
  assert.equal(rgbUrl.searchParams.get("g"), "3");
  assert.equal(rgbUrl.searchParams.get("b"), "1");
});

// Real backend answers (trimmed), captured from GET /patches/{id}/spectrum, /metrics and
// /models/event. The science panels crashed when these names drifted from the TS types.
test("science responses carry the fields the panels read", async () => {
  const { readFileSync } = await import("node:fs");
  const fx = JSON.parse(readFileSync(new URL("./fixtures/science-responses.json", import.meta.url), "utf8"));
  const spectrum: import("../lib/api").PatchSpectrumResponse = fx.spectrum;
  const metrics: import("../lib/api").PatchMetricsResponse = fx.metrics;
  const model1: import("../lib/api").Model1EventResponse = fx.model1;

  assert.equal(spectrum.channels.length, 102);
  for (const c of spectrum.channels) {
    assert.equal(typeof c.lambda_c_um, "number");
    assert.ok(c.flux_mjy === null || typeof c.flux_mjy === "number");
  }
  assert.deepEqual(spectrum.channels.filter((c) => c.is_blankch).map((c) => c.flux_mjy), [null, null]);
  assert.equal(typeof metrics.confidence.c_global, "number");
  assert.ok(model1.treeshap_values!.top_drivers!.every((d) => typeof d.phi === "number"));
});
