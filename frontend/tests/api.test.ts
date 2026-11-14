import { test } from "node:test";
import assert from "node:assert/strict";
import {
  validCoordinates,
  nextEpoch,
  releaseLabel,
  timeline,
  ApiError,
} from "../lib/api";
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
