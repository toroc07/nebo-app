// Pixel <-> sky coordinate conversion for one SPHEREx cutout.
//
// The backend delivers north-up / east-left images on a tangent-plane (gnomonic) grid centred
// on the patch position, which is the central pixel. So no WCS library is needed: the patch
// centre, the pixel scale and the image size are enough. Verified against the API's own
// `expected_position` and `sector.corners` (see tests/sky.test.ts).

export type SkyGrid = {
  /** Patch centre, ICRS degrees. It sits on the central pixel. */
  ra: number;
  dec: number;
  width: number;
  height: number;
  /** Arcseconds per pixel. */
  scaleArcsec: number;
};

export type SkyPoint = { ra: number; dec: number };
export type PixelPoint = { x: number; y: number };

const RAD = Math.PI / 180;
const ARCSEC = RAD / 3600;

/** Builds the grid from the fields of a `/timeline` response that matter here. */
export function gridFrom(t: {
  patch: { ra: number; dec: number };
  size: { width_px: number; height_px: number; pixel_scale_arcsec: number };
}): SkyGrid {
  return {
    ra: t.patch.ra,
    dec: t.patch.dec,
    width: t.size.width_px,
    height: t.size.height_px,
    scaleArcsec: t.size.pixel_scale_arcsec,
  };
}

// Pixel indices are 0-based and refer to pixel centres, so the image spans
// [-0.5, width - 0.5] horizontally and the central pixel is (width - 1) / 2.
function centre(g: SkyGrid): PixelPoint {
  return { x: (g.width - 1) / 2, y: (g.height - 1) / 2 };
}

/** Sky position of a pixel. x grows to the west (right), y grows to the south (down). */
export function pixelToSky(g: SkyGrid, x: number, y: number): SkyPoint {
  const c = centre(g);
  const s = g.scaleArcsec * ARCSEC;
  // Tangent-plane offsets in radians: xi grows east, eta grows north. East is on the left.
  const xi = -(x - c.x) * s;
  const eta = -(y - c.y) * s;
  const ra0 = g.ra * RAD;
  const dec0 = g.dec * RAD;
  const rho = Math.hypot(xi, eta);
  if (rho === 0) return { ra: g.ra, dec: g.dec };
  const cc = Math.atan(rho);
  const sinC = Math.sin(cc);
  const cosC = Math.cos(cc);
  const dec = Math.asin(
    cosC * Math.sin(dec0) + (eta * sinC * Math.cos(dec0)) / rho,
  );
  const ra =
    ra0 +
    Math.atan2(
      xi * sinC,
      rho * Math.cos(dec0) * cosC - eta * Math.sin(dec0) * sinC,
    );
  return { ra: normalizeRa(ra / RAD), dec: dec / RAD };
}

/** Pixel position of a sky coordinate (inverse of `pixelToSky`). */
export function skyToPixel(g: SkyGrid, ra: number, dec: number): PixelPoint {
  const c = centre(g);
  const s = g.scaleArcsec * ARCSEC;
  const dRa = (ra - g.ra) * RAD;
  const d = dec * RAD;
  const dec0 = g.dec * RAD;
  const cosC =
    Math.sin(dec0) * Math.sin(d) + Math.cos(dec0) * Math.cos(d) * Math.cos(dRa);
  const xi = (Math.cos(d) * Math.sin(dRa)) / cosC;
  const eta =
    (Math.cos(dec0) * Math.sin(d) -
      Math.sin(dec0) * Math.cos(d) * Math.cos(dRa)) /
    cosC;
  return { x: c.x - xi / s, y: c.y - eta / s };
}

function normalizeRa(ra: number): number {
  return ((ra % 360) + 360) % 360;
}

/** RA as hours, minutes, seconds: `17h 57m 47.09s`. */
export function formatRa(raDeg: number): string {
  // Work in hundredths of a second so rounding carries into minutes/hours correctly.
  const total = Math.round((normalizeRa(raDeg) / 15) * 3600 * 100);
  const wrapped = total % (24 * 3600 * 100);
  const h = Math.floor(wrapped / (3600 * 100));
  const m = Math.floor((wrapped % (3600 * 100)) / (60 * 100));
  const sec = (wrapped % (60 * 100)) / 100;
  return `${h}h ${String(m).padStart(2, "0")}m ${sec.toFixed(2).padStart(5, "0")}s`;
}

/** Declination as signed degrees, arcminutes, arcseconds: `+04° 46′ 04.1″`. */
export function formatDec(decDeg: number): string {
  // Tenths of an arcsecond keep the carry logic simple and match the display precision.
  const total = Math.round(Math.abs(decDeg) * 3600 * 10);
  // A value that rounds to zero is shown as +00°, never as a negative zero.
  const sign = decDeg < 0 && total > 0 ? "−" : "+";
  const d = Math.floor(total / (3600 * 10));
  const m = Math.floor((total % (3600 * 10)) / (60 * 10));
  const sec = (total % (60 * 10)) / 10;
  return `${sign}${String(d).padStart(2, "0")}° ${String(m).padStart(2, "0")}′ ${sec.toFixed(1).padStart(4, "0")}″`;
}
