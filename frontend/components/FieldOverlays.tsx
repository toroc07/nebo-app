"use client";
import { useLayoutEffect, useRef } from "react";
import type { CandidateDetection } from "@/lib/api";
import { FAST_MOVER_MAS_YR, type GaiaField } from "@/lib/lab/gaia";
import {
  changeLabel,
  labelledChanges,
  selectionId,
  trajectory,
  type Selection,
  type WiseField,
} from "@/lib/overlays";
import s from "./field.module.css";

/**
 * Catalog layers drawn over the field image. Coordinates are pixel indices of the PNG on
 * screen (north up, east left): pixel i covers [i, i + 1] of the box, so its centre is i + 0.5.
 * Markers are HTML buttons placed in percent, so they keep their on-screen size at any field size.
 */
export default function FieldOverlays({
  width,
  height,
  epoch,
  gaia,
  wise,
  changes,
  selected,
  onSelect,
}: {
  width: number;
  height: number;
  epoch: number;
  gaia: GaiaField | null;
  wise: WiseField | null;
  changes: CandidateDetection[] | null;
  selected: Selection | null;
  onSelect: (sel: Selection) => void;
}) {
  const at = (x: number, y: number) => ({
    left: `${((x + 0.5) / width) * 100}%`,
    top: `${((y + 0.5) / height) * 100}%`,
  });
  const inside = (x: number, y: number) =>
    x >= -0.5 && y >= -0.5 && x <= width - 0.5 && y <= height - 0.5;
  const selectedId = selected && selectionId(selected);
  const isSelected = (kind: Selection["kind"], id: string) =>
    selectedId === `${kind}:${id}`;

  const labelled = labelledChanges(changes ?? []);
  const overlay = useRef<HTMLDivElement>(null);
  // Place every badge where it covers no image button and stays inside the image.
  useLayoutEffect(() => {
    const root = overlay.current;
    if (!root) return;
    const place = () => placeBadges(root);
    place();
    const observer = new ResizeObserver(place);
    observer.observe(root);
    return () => observer.disconnect();
  }, [changes, width, height]);
  const fastStars = gaia?.stars.filter((star) => trajectory(star)) ?? [];

  return (
    <div ref={overlay} className={s.overlay}>
      {fastStars.length > 0 && (
        <svg
          className={s.paths}
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            <marker
              id="trajectory-arrow"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
            </marker>
          </defs>
          {fastStars.map((star) => {
            const t = trajectory(star)!;
            return (
              <line
                key={star.source_id}
                x1={t.from.x + 0.5}
                y1={t.from.y + 0.5}
                x2={t.to.x + 0.5}
                y2={t.to.y + 0.5}
                markerEnd="url(#trajectory-arrow)"
              />
            );
          })}
        </svg>
      )}

      {gaia?.stars.map((star) => {
        const p = star.positions[epoch];
        if (!p || !inside(p.x, p.y)) return null;
        const fast = (star.pm_total_mas_yr ?? 0) >= FAST_MOVER_MAS_YR;
        return (
          <button
            key={`g${star.source_id}`}
            type="button"
            className={`${s.mark} ${fast ? s.gaiaFast : s.gaiaMark}`}
            style={at(p.x, p.y)}
            // Background stars stay clickable but out of the tab order: a dense field holds hundreds.
            tabIndex={fast ? 0 : -1}
            aria-pressed={isSelected("gaia", star.source_id)}
            aria-label={`Gaia DR3 star${fast ? ", fast mover" : ""}, G ${star.g_mag?.toFixed(1) ?? "unknown"}`}
            onClick={() => onSelect({ kind: "gaia", star })}
          />
        );
      })}

      {wise?.sources.map((source) => {
        const p = source.positions[epoch];
        if (!p?.in_image) return null;
        return (
          <button
            key={`w${source.source_id}`}
            type="button"
            className={`${s.mark} ${source.cold_candidate ? s.coldMark : s.wiseMark}`}
            style={at(p.x, p.y)}
            tabIndex={source.cold_candidate ? 0 : -1}
            aria-pressed={isSelected("wise", source.source_id)}
            aria-label={
              source.cold_candidate
                ? "CatWISE cold candidate, no Gaia counterpart"
                : `CatWISE source, W2 ${source.w2_mag?.toFixed(1) ?? "unknown"}`
            }
            onClick={() => onSelect({ kind: "wise", source })}
          />
        );
      })}

      {changes?.map((change) => {
        const id = `${change.x},${change.y}`;
        const tone =
          change.classification === "catalogued_systematic"
            ? s.badgeSystematic
            : change.classification === "catalogued_object"
              ? s.badgeKnown
              : s.badgeNew;
        if (!labelled.has(id))
          return (
            <button
              key={`c${id}`}
              type="button"
              className={`${s.changeDot} ${tone}`}
              style={at(change.x, change.y)}
              tabIndex={-1}
              aria-pressed={isSelected("change", id)}
              aria-label={`${changeLabel(change)}, SNR ${change.snr.toFixed(1)}`}
              onClick={() => onSelect({ kind: "change", change })}
            />
          );
        return (
          <button
            key={`c${id}`}
            type="button"
            className={`${s.badge} ${tone}`}
            style={at(change.x, change.y)}
            // Placement order: new signals first, so they get the free spots.
            data-badge={tone === s.badgeNew ? 0 : tone === s.badgeKnown ? 1 : 2}
            aria-pressed={isSelected("change", id)}
            onClick={() => onSelect({ kind: "change", change })}
          >
            {changeLabel(change)}
          </button>
        );
      })}
    </div>
  );
}

/** Badge placements to try, in order: [vertical, horizontal]; undefined = above / centred. */
const PLACEMENTS: [string | undefined, string | undefined][] = [
  [undefined, undefined],
  ["below", undefined],
  [undefined, "right"],
  ["below", "right"],
  [undefined, "left"],
  ["below", "left"],
  ["mid", "after"],
  ["mid", "before"],
];

/**
 * Moves each change badge to the first placement that stays inside the image, overlaps no
 * `[data-image-tool]` button (Analysis, Difference, Alignment, Stack…) and, when it can, no badge
 * placed before it. A badge with no free placement keeps the default one, under the buttons.
 */
function placeBadges(root: HTMLElement) {
  const box = root.getBoundingClientRect();
  const tools = [...(root.parentElement?.querySelectorAll<HTMLElement>("[data-image-tool]") ?? [])]
    .map((e) => e.getBoundingClientRect())
    .filter((r) => r.width > 0);
  const hits = (a: DOMRect, b: DOMRect) =>
    a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  const placed: DOMRect[] = [];
  const badges = [...root.querySelectorAll<HTMLElement>("[data-badge]")].sort(
    (a, b) => Number(a.dataset.badge) - Number(b.dataset.badge),
  );
  for (const badge of badges) {
    const inside = (r: DOMRect) =>
      r.left >= box.left - 1 && r.right <= box.right + 1 && r.top >= box.top - 1 && r.bottom <= box.bottom + 1;
    const clear = (r: DOMRect) => inside(r) && !tools.some((t) => hits(r, t));
    // Best: clear of the buttons and of the badges already placed; else clear of the buttons only.
    const fits =
      PLACEMENTS.find(([v, h]) => {
        setPlacement(badge, v, h);
        const r = badge.getBoundingClientRect();
        return clear(r) && !placed.some((p) => hits(r, p));
      }) ??
      PLACEMENTS.find(([v, h]) => {
        setPlacement(badge, v, h);
        return clear(badge.getBoundingClientRect());
      });
    if (!fits) setPlacement(badge, undefined, undefined);
    placed.push(badge.getBoundingClientRect());
  }
}

function setPlacement(el: HTMLElement, v: string | undefined, h: string | undefined) {
  if (v) el.dataset.v = v;
  else delete el.dataset.v;
  if (h) el.dataset.h = h;
  else delete el.dataset.h;
}
