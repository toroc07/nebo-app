import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

// The viewer swaps between image sets in place, keeping zoom, pan, pin and epoch. That is only
// honest if the sets are the same data painted differently, so this pins that premise down.
// `npm test` runs from frontend/, and the demo exports live in ../shared.
const shared = path.join(process.cwd(), "..", "shared");
const sets = { gray: "demo", amber: "demo-color", inferno: "demo-inferno" };

function timeline(folder: string, file: string) {
  return JSON.parse(
    readFileSync(path.join(shared, folder, "timeline", file), "utf8"),
  );
}

/** What must be identical across palettes; ids, dates and image paths may legitimately differ. */
function content(t: {
  patch: { ra: number; dec: number; target: string | null };
  detector: unknown;
  size: unknown;
  sector: unknown;
  display: unknown;
  epochs: Record<string, unknown>[];
}) {
  return {
    patch: { ra: t.patch.ra, dec: t.patch.dec, target: t.patch.target },
    detector: t.detector,
    size: t.size,
    sector: t.sector,
    display: t.display,
    epochs: t.epochs.map(({ image_url: _url, ...rest }) => rest),
  };
}

const files = readdirSync(path.join(shared, sets.gray, "timeline")).filter(
  (f) => f.endsWith(".json"),
);

test("the three demo sets cover the same timelines", () => {
  assert.ok(files.length >= 30, `expected 30 timelines, found ${files.length}`);
  for (const folder of Object.values(sets)) {
    const own = readdirSync(path.join(shared, folder, "timeline")).filter((f) =>
      f.endsWith(".json"),
    );
    assert.deepEqual(own.sort(), [...files].sort(), folder);
  }
});

test("every timeline has identical epochs, positions and geometry in all palettes", () => {
  for (const file of files) {
    const gray = content(timeline(sets.gray, file));
    for (const palette of ["amber", "inferno"] as const) {
      assert.deepEqual(
        content(timeline(sets[palette], file)),
        gray,
        `${palette} differs from gray in ${file}`,
      );
    }
  }
});

test("every epoch image exists in its own folder and is a PNG", () => {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47]);
  for (const [palette, folder] of Object.entries(sets)) {
    for (const file of files) {
      for (const epoch of timeline(folder, file).epochs) {
        const image = path.join(shared, folder, epoch.image_url);
        assert.ok(existsSync(image), `${palette}: missing ${epoch.image_url}`);
        assert.deepEqual(
          readFileSync(image).subarray(0, 4),
          signature,
          `${palette}: ${epoch.image_url} is not a PNG`,
        );
      }
    }
  }
});

// The viewer shows the smallest of the three sizes that covers the screen and switches between
// them while zooming (lib/lab/fov.ts). That only works if they nest exactly: same centre, same
// pixel scale and epochs, and each smaller one centred inside the larger.
test("the three sizes of every observation nest as central crops", () => {
  const groups = new Map<string, string[]>();
  for (const file of files) {
    const key = file.replace(/_(small|medium|large)\.json$/, "");
    groups.set(key, [...(groups.get(key) ?? []), file]);
  }
  assert.ok(
    groups.size >= 10,
    `expected 10 observations, found ${groups.size}`,
  );
  for (const [key, group] of groups) {
    assert.equal(group.length, 3, `${key} should have small, medium and large`);
    const by = Object.fromEntries(
      group.map((f) => [
        f.match(/_(small|medium|large)\.json$/)![1],
        timeline(sets.gray, f),
      ]),
    );
    const { small, medium, large } = by;
    for (const t of [small, medium]) {
      assert.deepEqual(
        [t.patch.ra, t.patch.dec, t.size.pixel_scale_arcsec],
        [large.patch.ra, large.patch.dec, large.size.pixel_scale_arcsec],
        `${key}: same centre and pixel scale`,
      );
      assert.deepEqual(
        t.epochs.map((e: { start_utc: string }) => e.start_utc),
        large.epochs.map((e: { start_utc: string }) => e.start_utc),
        `${key}: same epochs`,
      );
    }
    assert.ok(
      small.size.width_px < medium.size.width_px &&
        medium.size.width_px < large.size.width_px,
      `${key}: sizes grow`,
    );
    // The expected position is the same star in every size, only indexed from a different corner.
    for (const [name, t] of [
      ["small", small],
      ["medium", medium],
    ] as const) {
      const off = (large.size.width_px - t.size.width_px) / 2;
      t.epochs.forEach(
        (e: { expected_position: { x: number; y: number } }, i: number) => {
          const L = large.epochs[i].expected_position;
          assert.ok(
            Math.abs(e.expected_position.x + off - L.x) < 1e-6,
            `${key} ${name} x`,
          );
          assert.ok(
            Math.abs(e.expected_position.y + off - L.y) < 1e-6,
            `${key} ${name} y`,
          );
        },
      );
    }
  }
});
