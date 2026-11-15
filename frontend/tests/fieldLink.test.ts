import { test } from "node:test";
import assert from "node:assert/strict";
import { parseFieldLink, fieldLink } from "../lib/fieldLink";

test("a coordinate link opens that field", () => {
  assert.deepEqual(parseFieldLink("?ra=133.795&dec=-7.245&fov=6&det=6"), {
    query: { ra: 133.795, dec: -7.245 },
    size: "medium",
    detector: 6,
    epoch: 0,
  });
});

test("detector is accepted as a long name for det", () => {
  assert.equal(parseFieldLink("?ra=133.795&dec=-7.245&detector=6")?.detector, 6);
});

test("a target link keeps detector optional", () => {
  assert.deepEqual(parseFieldLink("?target=wise-0855&fov=15&epoch=3"), {
    query: { target: "wise-0855" },
    size: "large",
    detector: undefined,
    epoch: 2,
  });
});

test("invalid or incomplete links are ignored", () => {
  for (const s of [
    "",
    "?fov=6",
    "?ra=400&dec=0",
    "?ra=10&dec=-91",
    "?ra=10",
    "?ra=&dec=",
    "?ra=abc&dec=0",
    "?ra=10&dec=0&det=7",
    "?ra=10&dec=0&det=2.5",
    "?ra=10&dec=0&fov=5",
    "?ra=10&dec=0&epoch=0",
    "?target=Bad%20Slug!",
    "?target=wise-0855&ra=10&dec=0",
  ])
    assert.equal(parseFieldLink(s), null, s);
});

test("the copied link reads back as the same field", () => {
  const url = fieldLink("https://nebo.app/", { ra: 133.795, dec: -7.245 }, "small", 6, 3);
  assert.equal(url, "https://nebo.app/?ra=133.795&dec=-7.245&fov=3&det=6&epoch=4");
  assert.deepEqual(parseFieldLink(new URL(url).search), {
    query: { ra: 133.795, dec: -7.245 },
    size: "small",
    detector: 6,
    epoch: 3,
  });
});
