"use client";
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
  const fastStars = gaia?.stars.filter((star) => trajectory(star)) ?? [];

  return (
    <div className={s.overlay}>
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
        const known = change.classification === "catalogued_object";
        if (!labelled.has(id))
          return (
            <button
              key={`c${id}`}
              type="button"
              className={`${s.changeDot} ${known ? s.badgeKnown : s.badgeNew}`}
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
            className={`${s.badge} ${known ? s.badgeKnown : s.badgeNew}`}
            style={at(change.x, change.y)}
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
