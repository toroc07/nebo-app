import type { Query } from "./api";

/** Field size names (backend `config.SIZES_DEG`) by side in arcminutes. */
const SIZE_BY_FOV: Record<string, string> = { "3": "small", "6": "medium", "15": "large" };

/** `epoch` is a 0-based index, as `Field` keeps it. */
/** `name` labels a field opened by coordinates (e.g. a suggested star that is not in the catalogue). */
export type FieldLink = { query: Query; size: string; detector?: number; epoch: number; name?: string };

/**
 * Reads a shareable field link: `?ra=&dec=` (ICRS degrees) or `?target=<slug>`, plus optional
 * `fov` (3, 6 or 15 arcmin), `det` (1–6; `detector` also accepted) and `epoch` (1 = first, as the viewer counts them). Anything invalid → null.
 */
export function parseFieldLink(search: string): FieldLink | null {
  const p = new URLSearchParams(search);
  const target = p.get("target"),
    ra = p.get("ra"),
    dec = p.get("dec"),
    fov = p.get("fov"),
    det = p.get("det") ?? p.get("detector"),
    epoch = p.get("epoch");
  let query: Query;
  if (target !== null) {
    if (ra !== null || dec !== null || !/^[a-z0-9-]{1,64}$/.test(target)) return null;
    query = { target };
  } else {
    if (ra === null || dec === null || ra.trim() === "" || dec.trim() === "") return null;
    const r = Number(ra),
      d = Number(dec);
    if (!(r >= 0 && r < 360 && d >= -90 && d <= 90)) return null;
    query = { ra: r, dec: d };
  }
  const size = fov === null ? "medium" : SIZE_BY_FOV[fov];
  if (!size) return null;
  const detector = det === null ? undefined : Number(det);
  if (detector !== undefined && !(Number.isInteger(detector) && detector >= 1 && detector <= 6)) return null;
  const e = epoch === null ? 1 : Number(epoch);
  if (!(Number.isInteger(e) && e >= 1)) return null;
  // Display-only label (React escapes it); a missing, empty or overlong one is dropped, not fatal.
  const name = p.get("name")?.trim();
  return { query, size, detector, epoch: e - 1, ...(name && name.length <= 80 && query.ra !== undefined ? { name } : {}) };
}

/** The shareable URL of a field as the viewer shows it now. */
export function fieldLink(base: string, query: Query, size: string, detector: number, epoch: number, name?: string) {
  const fov = Object.keys(SIZE_BY_FOV).find((k) => SIZE_BY_FOV[k] === size) ?? "6";
  const p = new URLSearchParams(
    query.target !== undefined ? { target: query.target } : { ra: String(query.ra), dec: String(query.dec) },
  );
  p.set("fov", fov);
  p.set("det", String(detector));
  p.set("epoch", String(epoch + 1));
  if (name && query.target === undefined) p.set("name", name);
  return `${base}?${p}`;
}
