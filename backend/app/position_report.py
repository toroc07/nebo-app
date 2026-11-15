"""Automatic validation of the catalogue targets' positions (P1-6).

For every catalogue target, chosen detector and SPHEREx epoch, compare where the object IS in
the epoch image (a centroid measured on the float32 ``.npz`` co-add) with where it SHOULD be
(``expected_position`` from ``GET /timeline``: the catalogue position propagated with proper
motion to the epoch's mid date). Passing means the offset is at most 1 pixel (6.15 arcsec).

This complements the Gaia check (``crossmatch.check_epoch_alignment``, ``/patches/{id}/alignment``),
which measures the residual shift of slow field stars: that one validates the image WCS, this
one validates the target ephemeris plus the WCS for the object the user is told to look at.

Run against the public API (read-only GET requests, nothing is written anywhere but ``--out``)::

    python -m app.position_report
    python -m app.position_report --api http://127.0.0.1:8000/api/v1 --out ../docs/position-validation.md
"""

from __future__ import annotations

import argparse
import io
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import config
from .crossmatch import _robust_sigma

DEFAULT_API = "https://nebo-backend-673540938891.us-central1.run.app/api/v1"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "docs" / "position-validation.md"
PASS_PX = 1.0
MIN_SNR = 5.0

# Detectors measured per target, and why. Saturation flags per exposure live in the database
# (``nasa_sector_exposures.saturated_near_target``) and are not part of the timeline payload, so
# the stars known to saturate every detector are listed here; NaN cores are also detected below.
CHOSEN_DETECTORS: dict[str, tuple[tuple[int, ...], str]] = {
    "barnards-star": (
        (1, 5),
        "Saturated in every detector. D1 and D5 have no NaN core pixels in any epoch (D2-D4 lose "
        "the core in some epochs). Its 10.4\"/yr motion (~1.7 px/yr) makes it the real test of "
        "the proper-motion propagation.",
    ),
    "eps-indi-b": ((3,), "Clean, unsaturated point source in D3 (S/N 100-230), 4 epochs."),
    "wise-0855": (
        (5, 6),
        "Only visible at the longest wavelengths: D5 detects it in all 4 epochs; D6 misses "
        "epoch 1, which is kept to show the no-detection case. In D1-D4 the fit lands on a "
        "fixed background source 0.7-2 px away, not the brown dwarf.",
    ),
    "rw-aurigae": (
        (1,),
        "Saturated in every detector; D1 has the lowest peak (least clipped) and no NaN core.",
    ),
    "r-draconis": (
        (6,),
        "Saturated Mira with NaN cores in every detector; D6 has the smallest hole (1-2 px) "
        "and the most epochs with that little damage (10).",
    ),
}
KNOWN_SATURATED = {"barnards-star", "rw-aurigae", "r-draconis"}


@dataclass(frozen=True)
class Centroid:
    """A measured position in the array's own pixel frame (x = column, y = row)."""

    x: float
    y: float
    snr: float
    nan_pixels: int  # NaN pixels inside the fit box (saturated cores come back without a value)
    method: str  # "gaussian" (2D Gaussian fit) or "centroid" (flux-weighted fallback)


def _annulus_stats(image: np.ndarray, cx: int, cy: int, r_in: float, r_out: float) -> tuple[float, float]:
    ny, nx = image.shape
    y0, y1 = max(0, int(cy - r_out)), min(ny, int(cy + r_out) + 1)
    x0, x1 = max(0, int(cx - r_out)), min(nx, int(cx + r_out) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    ring = image[y0:y1, x0:x1][(np.hypot(xx - cx, yy - cy) >= r_in) & (np.hypot(xx - cx, yy - cy) <= r_out)]
    ring = ring[np.isfinite(ring)]
    if ring.size < 5:
        return 0.0, 0.0
    return float(np.median(ring)), _robust_sigma(ring)


def _weighted_centroid(sub: np.ndarray, xx: np.ndarray, yy: np.ndarray) -> tuple[float, float] | None:
    weights = np.where(np.isfinite(sub), np.maximum(sub, 0.0), 0.0)
    total = float(weights.sum())
    if total <= 0.0:
        return None
    return float((weights * xx).sum() / total), float((weights * yy).sum() / total)


def _gaussian_fit(
    values: np.ndarray, xx: np.ndarray, yy: np.ndarray, start: tuple[float, float, float, float]
) -> tuple[float, float] | None:
    """Levenberg-Marquardt fit of ``bg + A exp(-r^2 / 2 s^2)`` to finite pixels only.

    NaN pixels are simply left out, so a saturated core without values is fitted from its wings.
    """
    amp, xc, yc, bg = start
    p = np.array([amp, xc, yc, 1.0, bg], dtype=np.float64)
    lam = 1e-2

    def residuals(q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a, x0, y0, s, b = q
        dx, dy = xx - x0, yy - y0
        g = np.exp(-(dx * dx + dy * dy) / (2.0 * s * s))
        model = b + a * g
        jac = np.column_stack(
            [g, a * g * dx / s**2, a * g * dy / s**2, a * g * (dx * dx + dy * dy) / s**3, np.ones_like(g)]
        )
        return values - model, jac

    res, jac = residuals(p)
    cost = float(res @ res)
    for _ in range(100):
        jtj = jac.T @ jac
        step = np.linalg.solve(jtj + lam * np.diag(np.diag(jtj) + 1e-12), jac.T @ res)
        trial = p + step
        if trial[3] <= 0.2:
            lam *= 10.0
            continue
        res_t, jac_t = residuals(trial)
        cost_t = float(res_t @ res_t)
        if cost_t < cost:
            converged = abs(cost - cost_t) <= 1e-10 * max(cost, 1e-30)
            p, res, jac, cost = trial, res_t, jac_t, cost_t
            lam = max(lam / 10.0, 1e-9)
            if converged:
                break
        else:
            lam *= 10.0
            if lam > 1e10:
                break
    a, x0, y0, s, _ = p
    if not (np.all(np.isfinite(p)) and a > 0 and 0.3 <= s <= 5.0):
        return None
    return float(x0), float(y0)


def measure_centroid(
    image: np.ndarray,
    variance: np.ndarray | None,
    x0: float,
    y0: float,
    box: int = 7,
    min_snr: float = MIN_SNR,
) -> Centroid | None:
    """Centroid of the source nearest (x0, y0), in the array's pixel frame; None if undetected.

    A ``box`` x ``box`` window around the expected pixel is background-subtracted (median of an
    annulus just outside it) and fitted with a 2D Gaussian using finite pixels only, so NaN
    (saturated) cores are measured from the PSF wings. A background-subtracted flux-weighted
    centroid (NaN pixels set to the window maximum, which is what a saturated core looks like)
    is the starting guess and the fallback. S/N is the background-subtracted peak over the
    per-pixel noise: the larger of the annulus scatter and the co-add's own sqrt(variance).
    """
    img = np.asarray(image, dtype=np.float64)
    ny, nx = img.shape
    half = box // 2
    cx, cy = int(round(x0)), int(round(y0))
    if not (half <= cx < nx - half and half <= cy < ny - half):
        return None
    bg, noise = _annulus_stats(img, cx, cy, half + 2, half + 7)
    sub = img[cy - half : cy + half + 1, cx - half : cx + half + 1] - bg
    yy, xx = np.mgrid[cy - half : cy + half + 1, cx - half : cx + half + 1].astype(np.float64)
    finite = np.isfinite(sub)
    nan_pixels = int((~finite).sum())
    if finite.sum() < max(6, sub.size // 3):
        return None

    if variance is not None:
        var = np.asarray(variance, dtype=np.float64)[cy - half : cy + half + 1, cx - half : cx + half + 1]
        good = np.isfinite(var) & (var > 0)
        if good.any():
            noise = max(noise, float(np.sqrt(np.median(var[good]))))
    peak = float(np.nanmax(sub))
    if noise <= 0.0 or peak <= 0.0:
        return None
    snr = peak / noise
    if snr < min_snr:
        return None

    filled = np.where(finite, sub, np.nanmax(sub)) if nan_pixels else sub
    start = _weighted_centroid(filled, xx, yy)
    if start is None:
        return None
    fit = _gaussian_fit(sub[finite], xx[finite], yy[finite], (peak, start[0], start[1], 0.0))
    if fit is not None and abs(fit[0] - x0) <= half and abs(fit[1] - y0) <= half:
        return Centroid(fit[0], fit[1], snr, nan_pixels, "gaussian")
    return Centroid(start[0], start[1], snr, nan_pixels, "centroid")


def mjd_to_date(mjd: float) -> str:
    return (datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=mjd)).strftime("%Y-%m-%d")


def measure_epoch(
    epoch: dict[str, Any], arrays: dict[str, np.ndarray], *, saturated_target: bool
) -> dict[str, Any]:
    """One report row: expected vs measured position for one epoch, both in PNG pixels."""
    exp = epoch["expected_position"]
    image = arrays["image"]
    side = image.shape[0]
    # The npz keeps FITS row order (row 0 = south); the PNG and expected_position are flipped.
    found = measure_centroid(image, arrays.get("variance"), exp["x"], side - 1 - exp["y"])
    row: dict[str, Any] = {
        "epoch": epoch["index"],
        "date": mjd_to_date(epoch["mid_mjd"]),
        "releases": epoch.get("releases") or [],
        "expected": (exp["x"], exp["y"]),
        "measured": None,
        "offset_px": None,
        "snr": None,
        "saturated": saturated_target,
        "nan_pixels": None,
        "method": None,
        "passed": False,
    }
    if found is None:
        return row
    mx, my = found.x, side - 1 - found.y
    row |= {
        "measured": (mx, my),
        "offset_px": math.hypot(mx - exp["x"], my - exp["y"]),
        "snr": found.snr,
        "saturated": saturated_target or found.nan_pixels > 0,
        "nan_pixels": found.nan_pixels,
        "method": found.method,
    }
    row["passed"] = row["offset_px"] <= PASS_PX
    return row


def _http_get(url: str) -> Any:
    import requests

    response = requests.get(url, timeout=180)
    response.raise_for_status()
    return response


def collect(
    api: str, *, all_detectors: bool = False, get: Callable[[str], Any] = _http_get
) -> list[dict[str, Any]]:
    """Query the API and measure every target x chosen detector (or all six) x epoch."""
    origin = api.split("/api/")[0]
    rows: list[dict[str, Any]] = []
    for target in get(f"{api}/targets").json():
        slug = target["slug"]
        detectors, _ = CHOSEN_DETECTORS.get(slug, ((target.get("recommended_detector") or 3,), ""))
        for detector in range(1, 7) if all_detectors else detectors:
            base = {"target": slug, "name": target["name"], "detector": detector,
                    "chosen": detector in detectors}
            response = get(f"{api}/timeline?target={slug}&detector={detector}&size=large")
            if response.status_code != 200:
                rows.append(base | {"error": f"timeline HTTP {response.status_code}"})
                continue
            for epoch in response.json()["epochs"]:
                if not epoch.get("expected_position") or not epoch.get("npz_url"):
                    rows.append(base | {"epoch": epoch["index"], "error": "no expected position or npz"})
                    continue
                with np.load(io.BytesIO(get(origin + epoch["npz_url"]).content)) as npz:
                    arrays = {key: npz[key] for key in npz.files}
                rows.append(base | measure_epoch(epoch, arrays, saturated_target=slug in KNOWN_SATURATED))
    return rows


def _motion_section(rows: list[dict[str, Any]]) -> list[str]:
    """Expected vs measured displacement between the first and last detected epoch.

    This also checks the orientation end to end: with a flipped axis, Barnard's Star (moving
    north ~1.7 px/yr) would be measured moving the wrong way.
    """
    lines = [
        "",
        "## Motion between the first and last detection",
        "",
        "Displacement in PNG pixels (+x = west, +y = south). A wrong row flip or proper-motion sign "
        "would show up here as a measured motion opposite to the expected one.",
        "",
        "| Target | Det. | Epochs | Expected dx, dy | Measured dx, dy | Difference px |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key in dict.fromkeys((r["target"], r["detector"]) for r in rows):
        hits = [r for r in rows if (r["target"], r["detector"]) == key and r.get("measured")]
        if len(hits) < 2:
            continue
        first, last = hits[0], hits[-1]
        edx, edy = (last["expected"][i] - first["expected"][i] for i in (0, 1))
        mdx, mdy = (last["measured"][i] - first["measured"][i] for i in (0, 1))
        lines.append(
            f"| {first['name']} | D{first['detector']} | {first['epoch'] + 1}-{last['epoch'] + 1} "
            f"| {edx:+.2f}, {edy:+.2f} | {mdx:+.2f}, {mdy:+.2f} | {math.hypot(mdx - edx, mdy - edy):.2f} |"
        )
    return lines


def _all_detectors_section(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "",
        "## All detectors (cross-check)",
        "",
        "The same measurement on every detector, so the choice above is not cherry-picked. "
        "Cells: detections within 1 px / detections (epochs), worst offset in px.",
        "",
        "| Target | " + " | ".join(f"D{d}" for d in range(1, 7)) + " |",
        "| --- |" + " --- |" * 6,
    ]
    for slug in dict.fromkeys(r["target"] for r in rows):
        cells = []
        for d in range(1, 7):
            group = [r for r in rows if r["target"] == slug and r["detector"] == d and "error" not in r]
            if not group:
                cells.append("-")
                continue
            hits = [r for r in group if r["measured"] is not None]
            worst = max((r["offset_px"] for r in hits), default=None)
            cells.append(
                f"{sum(r['passed'] for r in hits)}/{len(hits)} ({len(group)})"
                + ("" if worst is None else f", {worst:.2f}")
            )
        name = next(r["name"] for r in rows if r["target"] == slug)
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "WISE 0855 fails in D1-D4 as expected: it is invisible there and the fit lands on a "
        "fixed background source (about x 73.7, y 72.4 in every epoch) while the expected "
        "position of the brown dwarf moves towards it, so the offset shrinks epoch after epoch.",
    ]
    return lines


def render_markdown(
    rows: list[dict[str, Any]], api: str, all_rows: list[dict[str, Any]] | None = None
) -> str:
    scale = config.PIXEL_SCALE_ARCSEC
    measured = [r for r in rows if "error" not in r]
    detected = [r for r in measured if r["measured"] is not None]
    passed = [r for r in detected if r["passed"]]
    clean = [r for r in detected if not r["saturated"]]
    lines = [
        "# Target position validation",
        "",
        "<!-- Generated by `python -m app.position_report`; do not edit by hand. -->",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from `{api}`.",
        "",
        "For each catalogue target, chosen detector and SPHEREx epoch: the **expected** position "
        "(catalogue coordinates propagated with proper motion to the epoch's mid date, "
        "`expected_position` in `GET /timeline`) against the **measured** position (2D Gaussian "
        "fit to the float32 co-add `.npz`, finite pixels only, so saturated NaN cores are fitted "
        "from the PSF wings). Pixels are the large (15') PNG frame: 0-based, north up, row 0 at "
        f"the top; 1 px = {scale}\". A row passes when the offset is at most {PASS_PX:g} px.",
        "",
        "## Summary",
        "",
        f"- Epochs measured: {len(measured)}; detected: {len(detected)}; "
        f"within {PASS_PX:g} px: **{len(passed)}/{len(detected)}**.",
    ]
    if clean:
        worst_clean = max(clean, key=lambda r: r["offset_px"])
        lines.append(
            f"- Unsaturated detections: {sum(r['passed'] for r in clean)}/{len(clean)} pass; worst "
            f"{worst_clean['offset_px']:.2f} px ({worst_clean['offset_px'] * scale:.1f}\", "
            f"{worst_clean['name']} D{worst_clean['detector']} epoch {worst_clean['epoch'] + 1})."
        )
    if detected:
        worst = max(detected, key=lambda r: r["offset_px"])
        lines.append(
            f"- Worst overall: {worst['offset_px']:.2f} px ({worst['offset_px'] * scale:.1f}\", "
            f"{worst['name']} D{worst['detector']} epoch {worst['epoch'] + 1}"
            f"{', saturated' if worst['saturated'] else ''})."
        )
    missed = [r for r in measured if r["measured"] is None]
    if missed:
        lines.append(
            "- Not detected (S/N < "
            f"{MIN_SNR:g} near the expected pixel): "
            + ", ".join(f"{r['name']} D{r['detector']} epoch {r['epoch'] + 1}" for r in missed)
            + "."
        )
    errors = [r for r in rows if "error" in r]
    if errors:
        lines.append("- Not measured: " + ", ".join(
            f"{r['name']} D{r['detector']} ({r['error']})" for r in errors) + ".")
    lines += [
        "- Saturated rows are less precise: the core is clipped or missing, so the centre comes "
        "from the wings. Barnard's Star, RW Aurigae and R Draconis saturate every detector.",
        "- WISE 0855 in D5 is faint (S/N ~10) and blended with a background source 0.7-2 px "
        "away; its offsets all lean towards that source, so they bound the ephemeris error "
        "from above rather than measure it.",
        "- R Draconis and RW Aurigae barely move (proper motion under 0.01 px/yr): their expected "
        "position is the image centre in every epoch. Barnard's Star, Eps Indi B and WISE 0855 "
        "move 0.8-1.7 px/yr, so their rows test the proper-motion propagation.",
        "",
        "## Detectors chosen",
        "",
        "| Target | Detectors | Why |",
        "| --- | --- | --- |",
    ]
    for slug, (detectors, why) in CHOSEN_DETECTORS.items():
        name = next((r["name"] for r in rows if r["target"] == slug), slug)
        lines.append(f"| {name} | {', '.join(f'D{d}' for d in detectors)} | {why} |")
    lines += [
        "",
        "## Per epoch",
        "",
        "| Target | Det. | Epoch | Date (mid) | Release | Expected x, y | Measured x, y "
        "| Offset px | Offset \" | S/N | Pass |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['name']} | D{r['detector']} | {r.get('epoch', '-')} | | | | "
                         f"{r['error']} | | | | no |")
            continue
        ex, ey = r["expected"]
        release = ", ".join(x.upper() for x in r["releases"])
        if r["measured"] is None:
            lines.append(f"| {r['name']} | D{r['detector']} | {r['epoch'] + 1} | {r['date']} | {release} "
                         f"| {ex:.2f}, {ey:.2f} | not detected | | | < {MIN_SNR:g} | no |")
            continue
        mx, my = r["measured"]
        snr = f"{r['snr']:.0f}"
        if r["saturated"]:
            holes = f", {r['nan_pixels']} NaN px" if r["nan_pixels"] else ""
            snr = f"saturated{holes}"
        lines.append(
            f"| {r['name']} | D{r['detector']} | {r['epoch'] + 1} | {r['date']} | {release} "
            f"| {ex:.2f}, {ey:.2f} | {mx:.2f}, {my:.2f} | {r['offset_px']:.2f} "
            f"| {r['offset_px'] * scale:.1f} | {snr} | {'yes' if r['passed'] else '**no**'} |"
        )
    lines += _motion_section(rows)
    if all_rows:
        lines += _all_detectors_section(all_rows)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=DEFAULT_API, help="API base URL, ending in /api/v1")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="markdown report to write")
    parser.add_argument(
        "--all-detectors", action="store_true", help="also measure D1-D6 for a cross-check table"
    )
    args = parser.parse_args(argv)
    api = args.api.rstrip("/")
    all_rows = collect(api, all_detectors=True) if args.all_detectors else None
    rows = (
        [r for r in all_rows if r["chosen"]]
        if all_rows is not None
        else collect(api)
    )
    args.out.write_text(render_markdown(rows, api, all_rows), encoding="utf-8")
    detected = [r for r in rows if r.get("measured") is not None]
    print(f"{sum(r['passed'] for r in detected)}/{len(detected)} detections within {PASS_PX:g} px; "
          f"report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
