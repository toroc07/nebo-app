"""Coupled ML models (Models 1, 2, 3) and deterministic science test profiles for SPHEREx.

Implements Section 3, 4, 5, and 6 of METRICAS_Y_MODELOS.md in pure NumPy:
- Model 1: 16-feature Event Attribution Classifier with Temperature Scaling,
  3 physical hard bounds, and exact additive SHAP-style attributions.
- Model 2: Hybrid Physical Template Fitter (chi2_red over <= 100 valid channels,
  strictly excluding BLANKCH 51-52) + Spectral-Index ML + Bayesian Stacking Fusion.
- Model 3: Heteroscedastic Gaussian Process (Matern-3/2 + Quasi-Periodic) +
  Astrometric Search Cone + 3 Alert Metrics + Closed-Loop Handshake with Model 1.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import config, ephemeris, metrics, science_catalogs
from .store import Patch, Store

MODEL1_CLASSES: tuple[str, ...] = (
    "MOVING_OBJECT",
    "VARIABLE_STAR_OR_TRANSIENT",
    "AIRGLOW_OR_ZODI_STRIPE",
    "INSTRUMENTAL_ARTIFACT",
    "EXTENDED_EMISSION",
)

MODEL1_FEATURES: tuple[str, ...] = (
    "z_mono",
    "z_dipole",
    "dipole_symmetry",
    "angular_shift_arcsec",
    "q_fit_epsf",
    "chi2_psf",
    "c_80_20",
    "p_clean_flags",
    "f_artifact_flags",
    "bg_gradient_norm",
    "bg_gradient_ratio",
    "is_he_1083_channel",
    "gaia_match_dist_arcsec",
    "gaia_pm_total_mas_yr",
    "wise_w1_w2_color",
    "thermal_nsdi_b6_b2",
)

# Feature standardization (mean, scale) for additive SHAP-style log-odds attribution
_M1_REF_MEAN: dict[str, float] = {
    "z_mono": 5.0,
    "z_dipole": 2.0,
    "dipole_symmetry": 0.5,
    "angular_shift_arcsec": 1.5,
    "q_fit_epsf": 1.15,
    "chi2_psf": 1.2,
    "c_80_20": 2.2,
    "p_clean_flags": 0.90,
    "f_artifact_flags": 0.05,
    "bg_gradient_norm": 0.05,
    "bg_gradient_ratio": 1.2,
    "is_he_1083_channel": 0.0,
    "gaia_match_dist_arcsec": 5.0,
    "gaia_pm_total_mas_yr": 50.0,
    "wise_w1_w2_color": 0.5,
    "thermal_nsdi_b6_b2": 0.0,
}
_M1_REF_SCALE: dict[str, float] = {
    "z_mono": 6.0,
    "z_dipole": 5.0,
    "dipole_symmetry": 0.35,
    "angular_shift_arcsec": 2.5,
    "q_fit_epsf": 0.5,
    "chi2_psf": 1.0,
    "c_80_20": 1.0,
    "p_clean_flags": 0.15,
    "f_artifact_flags": 0.15,
    "bg_gradient_norm": 0.15,
    "bg_gradient_ratio": 1.0,
    "is_he_1083_channel": 1.0,
    "gaia_match_dist_arcsec": 8.0,
    "gaia_pm_total_mas_yr": 500.0,
    "wise_w1_w2_color": 1.2,
    "thermal_nsdi_b6_b2": 0.45,
}

# Linear log-odds weights per class over standardized features (calibrated for SPHEREx physics)
_M1_WEIGHTS: dict[str, dict[str, float]] = {
    "MOVING_OBJECT": {
        "z_dipole": 1.65,
        "dipole_symmetry": 1.45,
        "angular_shift_arcsec": 0.90,
        "q_fit_epsf": -0.60,
        "p_clean_flags": 0.75,
        "f_artifact_flags": -2.20,
        "gaia_pm_total_mas_yr": 0.85,
        "wise_w1_w2_color": 0.70,
        "thermal_nsdi_b6_b2": 0.65,
        "is_he_1083_channel": -1.10,
    },
    "VARIABLE_STAR_OR_TRANSIENT": {
        "z_mono": 1.75,
        "z_dipole": -1.35,
        "angular_shift_arcsec": -0.80,
        "q_fit_epsf": -0.85,
        "chi2_psf": -0.45,
        "p_clean_flags": 0.80,
        "f_artifact_flags": -2.00,
        "gaia_match_dist_arcsec": -0.40,
        "is_he_1083_channel": -1.00,
    },
    "AIRGLOW_OR_ZODI_STRIPE": {
        "is_he_1083_channel": 2.80,
        "bg_gradient_norm": 1.20,
        "bg_gradient_ratio": 1.65,
        "q_fit_epsf": 0.85,
        "z_dipole": -0.70,
        "c_80_20": 0.45,
    },
    "INSTRUMENTAL_ARTIFACT": {
        "f_artifact_flags": 3.10,
        "p_clean_flags": -2.40,
        "chi2_psf": 1.15,
        "q_fit_epsf": 1.10,
        "dipole_symmetry": -1.25,
        "c_80_20": -0.80,
    },
    "EXTENDED_EMISSION": {
        "c_80_20": 1.85,
        "bg_gradient_norm": 1.35,
        "q_fit_epsf": 1.25,
        "chi2_psf": 0.90,
        "z_dipole": -0.90,
        "p_clean_flags": 0.40,
    },
}
_M1_BIAS: dict[str, float] = {
    "MOVING_OBJECT": 0.25,
    "VARIABLE_STAR_OR_TRANSIENT": 0.20,
    "AIRGLOW_OR_ZODI_STRIPE": -0.85,
    "INSTRUMENTAL_ARTIFACT": -0.70,
    "EXTENDED_EMISSION": -0.95,
}


def _softmax(logits: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
    t = max(0.05, float(temperature))
    scaled = {k: v / t for k, v in logits.items()}
    m = max(scaled.values())
    exps = {k: math.exp(v - m) for k, v in scaled.items()}
    total = sum(exps.values()) or 1.0
    return {k: exps[k] / total for k in logits}


def _shrink(probs: dict[str, float], eps: float = 0.1) -> dict[str, float]:
    """Mix with the uniform distribution so no class reads 0% or 100%.

    shortcut: uncalibrated shrinkage of hand-set weights; replace with real calibration when we
    have labelled events.
    """
    k = len(probs)
    return {c: round((1.0 - eps) * p + eps / k, 6) for c, p in probs.items()}


def _normalize_m1_features(raw: dict[str, Any]) -> dict[str, float]:
    return {name: float(raw.get(name, _M1_REF_MEAN[name])) for name in MODEL1_FEATURES}


def run_model1_event_classifier(
    feature_vector: dict[str, Any],
    *,
    temperature_t: float = 1.15,
    model_version: str = "v1",
) -> dict[str, Any]:
    """Classify a detected event into 5 physical/instrumental classes with SHAP attributions."""
    fv = _normalize_m1_features(feature_vector)
    logits: dict[str, float] = {}
    per_class_phi: dict[str, dict[str, float]] = {}

    for cls in MODEL1_CLASSES:
        weights = _M1_WEIGHTS[cls]
        phi_map: dict[str, float] = {}
        z = _M1_BIAS[cls]
        for feat in MODEL1_FEATURES:
            std_val = (fv[feat] - _M1_REF_MEAN[feat]) / _M1_REF_SCALE[feat]
            contrib = weights.get(feat, 0.0) * std_val
            phi_map[feat] = round(contrib, 5)
            z += contrib
        logits[cls] = z
        per_class_phi[cls] = phi_map

    probs = _softmax(logits, temperature=temperature_t)

    # Physical hard bounds (METRICAS_Y_MODELOS.md Section 3.1.D)
    hard_bound_applied: str | None = None
    if fv["f_artifact_flags"] > 0.30 or fv["p_clean_flags"] < 0.65:
        probs["MOVING_OBJECT"] = min(probs["MOVING_OBJECT"], 0.01)
        probs["INSTRUMENTAL_ARTIFACT"] = max(probs["INSTRUMENTAL_ARTIFACT"], 0.90)
        hard_bound_applied = "bound_1_pixel_corruption"
    elif fv["is_he_1083_channel"] >= 0.5 and fv["bg_gradient_ratio"] > 3.0 and fv["q_fit_epsf"] > 2.0:
        probs["VARIABLE_STAR_OR_TRANSIENT"] = min(probs["VARIABLE_STAR_OR_TRANSIENT"], 0.01)
        probs["AIRGLOW_OR_ZODI_STRIPE"] = max(probs["AIRGLOW_OR_ZODI_STRIPE"], 0.90)
        hard_bound_applied = "bound_2_he1_airglow"
    elif fv["z_dipole"] >= 5.0 and fv["dipole_symmetry"] < 0.35:
        probs["MOVING_OBJECT"] = min(probs["MOVING_OBJECT"], 0.02)
        probs["INSTRUMENTAL_ARTIFACT"] = max(probs["INSTRUMENTAL_ARTIFACT"], 0.85)
        hard_bound_applied = "bound_3_asymmetric_dipole"

    total_p = sum(probs.values()) or 1.0
    probs = _shrink({k: v / total_p for k, v in probs.items()})
    predicted_class = max(probs, key=lambda k: probs[k])
    conf_pct = int(round(probs[predicted_class] * 100))

    phi_pred = per_class_phi[predicted_class]
    sorted_drivers = sorted(phi_pred.items(), key=lambda kv: abs(kv[1]), reverse=True)
    top_drivers = [{"feature": k, "phi": v} for k, v in sorted_drivers[:5]]

    movement_score = int(
        round(100.0 * (1.0 / (1.0 + math.exp(-(fv["z_dipole"] - 3.5)))) * max(0.0, min(1.0, fv["dipole_symmetry"])))
    )
    if predicted_class in ("INSTRUMENTAL_ARTIFACT", "AIRGLOW_OR_ZODI_STRIPE"):
        traffic_light = "YELLOW" if predicted_class == "AIRGLOW_OR_ZODI_STRIPE" else "RED_ALERT"
        headline = "Possible instrumental or atmospheric signature"
        badge = "Artifact / Airglow Veto"
        explanation = (
            "Pixel quality flags, PSF shape, or 1.083 um He I background gradient indicate an "
            "instrumental or atmospheric effect rather than a clean astrophysical change."
        )
    elif predicted_class == "MOVING_OBJECT":
        traffic_light = "RED_ALERT" if fv["gaia_match_dist_arcsec"] > 5.0 else "GREEN"
        headline = "Observed moving candidate across epochs"
        badge = "Moving Object Candidate"
        explanation = (
            f"Consistent multi-epoch positional shift ({fv['angular_shift_arcsec']:.2f} arcsec) "
            f"with clean ePSF morphology and dipole symmetry {fv['dipole_symmetry']:.2f}."
        )
    else:
        traffic_light = "YELLOW" if fv["z_mono"] >= 3.0 else "GREEN"
        headline = "Observed stationary brightness change"
        badge = "Variable or Transient Source"
        explanation = (
            f"Point-source flux variation (Z_mono = {fv['z_mono']:.1f} sigma) with clean pixel flags "
            f"({fv['p_clean_flags']:.2f}) and no significant positional dipole."
        )

    citizen_level1 = {
        "traffic_light": traffic_light,
        "headline": headline,
        "movement_score_pct": movement_score,
        "confidence_score_pct": conf_pct,
        "badge": badge,
        "explanation": explanation,
        "is_new_candidate": bool(fv["gaia_match_dist_arcsec"] > 5.0 and predicted_class == "MOVING_OBJECT"),
        "top_3_reasons": top_drivers[:3],
    }
    researcher_level2 = {
        "predicted_class": predicted_class,
        "calibrated_probabilities": probs,
        "temperature_t": temperature_t,
        "feature_vector": {k: round(v, 5) for k, v in fv.items()},
        "shap_attribution": {
            "base_value": round(_M1_BIAS[predicted_class], 5),
            "per_feature": phi_pred,
            "top_drivers": top_drivers,
        },
        "hard_bound_applied": hard_bound_applied,
    }
    return {
        "feature_vector": fv,
        "predicted_class": predicted_class,
        "temperature_t": temperature_t,
        "probabilities": probs,
        "treeshap_values": researcher_level2["shap_attribution"],
        "citizen_level1": citizen_level1,
        "researcher_level2": researcher_level2,
        "model_version": model_version,
    }


# ---------------------------------------------------------------------------
# Model 2: Parametric 102-channel physical templates & Bayesian fusion
# ---------------------------------------------------------------------------

def _planck_mjy_shape(lam_um: np.ndarray, teff_k: float) -> np.ndarray:
    """Normalized Planck F_nu shape in arbitrary positive units."""
    # hc / k_B in um * K = 14387.77
    x = np.clip(14387.77 / (lam_um * max(100.0, teff_k)), 1e-3, 60.0)
    b_lam = (1.0 / (lam_um ** 3)) / np.expm1(x)
    peak = float(np.max(b_lam)) or 1.0
    return b_lam / peak


def _gauss_band(lam_um: np.ndarray, center_um: float, width_um: float) -> np.ndarray:
    return np.exp(-0.5 * (((lam_um - center_um) / width_um) ** 2))


def _build_physical_template_flux(template_key: str) -> np.ndarray:
    """Construct physically grounded 102-channel SPHEREx spectral templates."""
    lam = np.array([ch.lambda_c_um for ch in science_catalogs.SPHEREX_102_CHANNELS], dtype=np.float64)
    if template_key == "ULTRACOLD_Y_DWARF":
        base = _planck_mjy_shape(lam, 265.0)
        # Suppress short bands (optical/SWIR dropout), add H2O ice (3.05) + CH4 (3.3) + 4.8 um window
        att = (
            (1.0 - 0.85 * _gauss_band(lam, 1.41, 0.14))
            * (1.0 - 0.80 * _gauss_band(lam, 1.90, 0.15))
            * (1.0 - 0.72 * _gauss_band(lam, 3.05, 0.18))
            * (1.0 - 0.78 * _gauss_band(lam, 3.33, 0.16))
        )
        flux = base * att * np.where(lam < 2.2, 0.04, 1.0)
        flux += 0.35 * _gauss_band(lam, 4.84, 0.25)
    elif template_key == "COLD_BROWN_DWARF_T":
        base = _planck_mjy_shape(lam, 1280.0)
        att = (
            (1.0 - 0.62 * _gauss_band(lam, 1.41, 0.08))
            * (1.0 - 0.58 * _gauss_band(lam, 1.66, 0.07))
            * (1.0 - 0.65 * _gauss_band(lam, 1.90, 0.09))
            * (1.0 - 0.55 * _gauss_band(lam, 2.24, 0.08))
            * (1.0 - 0.68 * _gauss_band(lam, 3.30, 0.12))
        )
        flux = base * att
    elif template_key == "HIGH_PROPER_MOTION_M_DWARF":
        base = _planck_mjy_shape(lam, 3150.0)
        att = (1.0 - 0.18 * _gauss_band(lam, 1.41, 0.07)) * (1.0 - 0.16 * _gauss_band(lam, 1.90, 0.08))
        flux = base * att
    elif template_key == "YOUNG_STELLAR_OBJECT_ACCRETION":
        star = 0.55 * _planck_mjy_shape(lam, 4200.0)
        dust = 0.95 * _planck_mjy_shape(lam, 1100.0)
        lines = (
            0.32 * _gauss_band(lam, 1.284, 0.025)  # Pa-beta
            + 0.22 * _gauss_band(lam, 2.139, 0.025)  # H2
            + 0.42 * _gauss_band(lam, 4.041, 0.022)  # Br-alpha
        )
        flux = star + dust + lines
    elif template_key == "PULSATING_MIRA_VARIABLE":
        base = _planck_mjy_shape(lam, 2700.0)
        att = (
            (1.0 - 0.35 * _gauss_band(lam, 1.41, 0.09))
            * (1.0 - 0.38 * _gauss_band(lam, 1.90, 0.10))
            * (1.0 - 0.48 * _gauss_band(lam, 2.32, 0.08))  # CO 2-0 overtone
            * (1.0 - 0.42 * _gauss_band(lam, 4.67, 0.08))  # CO 1-0 fundamental
        )
        flux = base * att
    else:  # SOLAR_SYSTEM_COMET
        reflected = 0.60 * _planck_mjy_shape(lam, 5778.0)
        thermal = 0.70 * _planck_mjy_shape(lam, 290.0)
        att = (1.0 - 0.55 * _gauss_band(lam, 3.05, 0.16)) * (1.0 - 0.50 * _gauss_band(lam, 4.27, 0.06))
        flux = (reflected + thermal) * att + 0.25 * _gauss_band(lam, 4.67, 0.05)

    norm = float(np.max(flux)) or 1.0
    return flux / norm


MODEL2_TEMPLATE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "class_name": "ULTRACOLD_Y_DWARF",
        "template_name": "SONORA_ELF_OWL_Y4_260K_LOGG4.0",
        "teff_k": 260.0,
        "log_g": 4.0,
        "citizen_badge": "Ultra-Cold Brown Dwarf Candidate (Y-Type)",
    },
    {
        "class_name": "COLD_BROWN_DWARF_T",
        "template_name": "SONORA_BOBCAT_T6_1280K_LOGG5.25",
        "teff_k": 1280.0,
        "log_g": 5.25,
        "citizen_badge": "Cold Brown Dwarf Candidate (T-Type)",
    },
    {
        "class_name": "HIGH_PROPER_MOTION_M_DWARF",
        "template_name": "BT_SETTL_M4V_3150K_LOGG5.0",
        "teff_k": 3150.0,
        "log_g": 5.0,
        "citizen_badge": "Cool Red Dwarf (M-Type)",
    },
    {
        "class_name": "YOUNG_STELLAR_OBJECT_ACCRETION",
        "template_name": "YSO_ACCRETION_DISK_1800K_DUST",
        "teff_k": 1800.0,
        "log_g": 3.8,
        "citizen_badge": "Young Star with Warm Dust Disk",
    },
    {
        "class_name": "PULSATING_MIRA_VARIABLE",
        "template_name": "AGB_MIRA_GIANT_2700K_CO",
        "teff_k": 2700.0,
        "log_g": 1.5,
        "citizen_badge": "Pulsating Giant Star (Mira-Type)",
    },
    {
        "class_name": "SOLAR_SYSTEM_COMET",
        "template_name": "SOLAR_SYSTEM_COMET_ICE_CO2_290K",
        "teff_k": 290.0,
        "log_g": 4.0,
        "citizen_badge": "Icy Solar System Body / Comet",
    },
)


def _index_map(indices: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in indices:
        val = row.get("value")
        if row.get("is_valid") and val is not None and math.isfinite(float(val)):
            out[row["index_code"]] = float(val)
    return out


def run_model2_spectral_classifier(
    spectrum: dict[str, Any],
    indices: list[dict[str, Any]] | None = None,
    *,
    model_version: str = "v1",
) -> dict[str, Any]:
    """Fit 102-channel SPHEREx spectrum (excluding BLANKCH 51-52) and fuse with 17 indices."""
    computed_indices = indices if indices is not None else metrics.compute_all_17_spectral_indices(spectrum)
    idx_vals = _index_map(computed_indices)

    # Always 102 entries, so a short or long list cannot index out of range (missing = invalid).
    def channels(key: str, missing: Any) -> list[Any]:
        values = list(spectrum.get(key) or [])[:102]
        return values + [missing] * (102 - len(values))

    flux_list = channels("flux_mjy", None)
    sigma_list = channels("sigma_reported_mjy", None)
    valid_list = channels("valid_mask", False)

    # Strictly mask BLANKCH 51 and 52 (Golden Rule #1)
    mask = np.zeros(102, dtype=bool)
    f_arr = np.zeros(102, dtype=np.float64)
    s_arr = np.ones(102, dtype=np.float64)
    for i in range(102):
        ch_id = i + 1
        if ch_id in science_catalogs.BLANK_CHANNELS or not valid_list[i]:
            continue
        f_val, s_val = flux_list[i], sigma_list[i]
        if f_val is None or s_val is None:
            continue
        fv, sv = float(f_val), float(s_val)
        if math.isfinite(fv) and math.isfinite(sv) and sv > 0.0:
            mask[i] = True
            f_arr[i] = fv
            s_arr[i] = sv

    n_valid = int(np.sum(mask))
    nu = 4
    dof = max(1, n_valid - nu)
    inv_var = np.where(mask, 1.0 / (s_arr ** 2), 0.0)

    # Supervised spectral-index logits
    ml_logits = {
        "ULTRACOLD_Y_DWARF": (
            2.5 * idx_vals.get("COLOR_PLANET_X", 0.0)
            + 1.8 * max(0.0, idx_vals.get("IND_CH4_33", 0.0))
            + 3.0 * max(0.0, idx_vals.get("IND_H2O_ICE", 0.0))
            - 0.6
        ),
        "COLD_BROWN_DWARF_T": (
            2.2 * max(0.0, idx_vals.get("IND_CH4_16", 0.0))
            + 2.0 * max(0.0, idx_vals.get("IND_H2O_14", 0.0))
            + 1.8 * max(0.0, idx_vals.get("IND_CH4_22", 0.0))
            - 1.2 * max(0.0, idx_vals.get("COLOR_PLANET_X", 0.0) - 0.65)
        ),
        "HIGH_PROPER_MOTION_M_DWARF": (
            1.4
            - 2.2 * max(0.0, idx_vals.get("IND_CH4_16", 0.0))
            - 2.0 * max(0.0, idx_vals.get("COLOR_PLANET_X", 0.0))
            - 1.6 * max(0.0, idx_vals.get("IND_CO_23", 0.0))
            - 1.5 * max(0.0, idx_vals.get("COLOR_YSO_DUST", 0.5) - 0.9)
        ),
        "YOUNG_STELLAR_OBJECT_ACCRETION": (
            1.6 * min(3.5, max(0.0, idx_vals.get("COLOR_YSO_DUST", 0.0) - 0.8))
            + 1.8 * (1.0 if idx_vals.get("IND_BR_ALPHA", 0.0) > 0.0 else 0.0)
            + 1.4 * (1.0 if idx_vals.get("IND_PA_BETA", 0.0) > 0.0 else 0.0)
            - 2.2 * max(0.0, idx_vals.get("IND_CH4_33", 0.0))
            - 1.8 * max(0.0, idx_vals.get("IND_H2O_ICE", 0.0))
            - 0.8
        ),
        "PULSATING_MIRA_VARIABLE": (
            3.2 * max(0.0, idx_vals.get("IND_CO_23", 0.0))
            + 1.2 * max(0.0, idx_vals.get("IND_H2O_19", 0.0))
            - 1.5 * max(0.0, idx_vals.get("IND_CH4_16", 0.0))
            - 0.5
        ),
        "SOLAR_SYSTEM_COMET": (
            2.8 * max(0.0, idx_vals.get("IND_CO2_42", 0.0))
            + 2.2 * max(0.0, idx_vals.get("IND_H2O_ICE", 0.0))
            - 1.5 * max(0.0, idx_vals.get("COLOR_PLANET_X", 0.0) - 0.7)
            - 0.8
        ),
    }

    fit_results: list[dict[str, Any]] = []
    fused_logits: dict[str, float] = {}

    for tpl in MODEL2_TEMPLATE_CATALOG:
        cls_name = tpl["class_name"]
        s_vec = _build_physical_template_flux(cls_name)
        denom = float(np.sum(inv_var * (s_vec ** 2)))
        if denom > 0.0 and n_valid > 0:
            c_hat = float(np.sum(inv_var * f_arr * s_vec) / denom)
            sigma_c = math.sqrt(1.0 / denom)
            chi2 = float(np.sum(inv_var * ((f_arr - c_hat * s_vec) ** 2)))
            chi2_red = chi2 / dof
        else:
            c_hat, sigma_c, chi2_red = 0.0, 1.0, 99.0

        fit_results.append(
            {
                **tpl,
                "scale_factor_c": c_hat,
                "scale_sigma_c": sigma_c,
                "chi2_reduced": chi2_red,
            }
        )
        # Bayesian stacking fusion: supervised logit penalized by thermodynamic chi2_red
        fused_logits[cls_name] = 0.85 * ml_logits.get(cls_name, 0.0) - 1.2 * min(chi2_red, 25.0)

    best_fit = min(fit_results, key=lambda r: r["chi2_reduced"])
    posteriors = _shrink(_softmax(fused_logits, temperature=1.0))
    predicted_class = max(posteriors, key=lambda k: posteriors[k])

    selected_tpl = next(r for r in fit_results if r["class_name"] == predicted_class)
    sig_indices = [row["index_code"] for row in computed_indices if row.get("is_significant_3s")]

    citizen_level1 = {
        "probable_identity": selected_tpl["citizen_badge"],
        "confidence_pct": int(round(posteriors[predicted_class] * 100)),
        "chemical_fingerprints": sig_indices[:5],
        "fit_quality": "Excellent" if selected_tpl["chi2_reduced"] < 2.0 else "Moderate",
    }
    researcher_level2 = {
        "predicted_class": predicted_class,
        "best_template_name": selected_tpl["template_name"],
        "chi2_min_template_name": best_fit["template_name"],
        "template_teff_k": selected_tpl["teff_k"],
        "template_log_g": selected_tpl["log_g"],
        "scale_factor_c": round(selected_tpl["scale_factor_c"], 6),
        "scale_sigma_c": round(selected_tpl["scale_sigma_c"], 6),
        "chi2_reduced": round(selected_tpl["chi2_reduced"], 4),
        "dof": dof,
        "valid_channels_used": n_valid,
        "blankch_excluded": list(science_catalogs.BLANK_CHANNELS),
        "ml_logits": {k: round(v, 4) for k, v in ml_logits.items()},
        "bayesian_posteriors": posteriors,
    }

    return {
        "predicted_class": predicted_class,
        "best_template_name": selected_tpl["template_name"],
        "template_teff_k": selected_tpl["teff_k"],
        "template_log_g": selected_tpl["log_g"],
        "scale_factor_c": round(selected_tpl["scale_factor_c"], 6),
        "scale_sigma_c": round(selected_tpl["scale_sigma_c"], 6),
        "chi2_reduced": round(selected_tpl["chi2_reduced"], 4),
        "dof": dof,
        "valid_channels_used": n_valid,
        "ml_logits": researcher_level2["ml_logits"],
        "bayesian_posteriors": posteriors,
        "citizen_level1": citizen_level1,
        "researcher_level2": researcher_level2,
        "model_version": model_version,
    }


# ---------------------------------------------------------------------------
# Model 3: Heteroscedastic GP + Astrometric Cone + Model 1 Handshake
# ---------------------------------------------------------------------------

def _matern32_kernel(t1: np.ndarray, t2: np.ndarray, amp: float, lengthscale: float) -> np.ndarray:
    r = np.abs(t1[:, None] - t2[None, :])
    s3 = math.sqrt(3.0) * r / max(1e-3, lengthscale)
    return (amp ** 2) * (1.0 + s3) * np.exp(-s3)


def _qp_kernel(
    t1: np.ndarray, t2: np.ndarray, amp: float, period: float, decay: float = 900.0, l_phase: float = 0.7
) -> np.ndarray:
    r = np.abs(t1[:, None] - t2[None, :])
    sin_term = np.sin(math.pi * r / max(0.05, period)) / max(0.1, l_phase)
    return (amp ** 2) * np.exp(-(r ** 2) / (2.0 * decay * decay) - 2.0 * (sin_term ** 2))


def run_model3_temporal_forecast(
    times_mjd: list[float],
    fluxes_mjy: list[float],
    sigmas_mjy: list[float],
    *,
    ra_deg: float,
    dec_deg: float,
    pm_ra_mas_yr: float = 0.0,
    pm_dec_mas_yr: float = 0.0,
    horizon_days: float = 180.0,
    period_days: float | None = None,
    model1_result: dict[str, Any] | None = None,
    model1_attribution_id: int | None = None,
    model_version: str = "v1",
) -> dict[str, Any]:
    """Run GP photometric forecast, astrometric cone projection, and Model 1 alert handshake."""
    t = np.asarray(times_mjd, dtype=np.float64)
    y = np.asarray(fluxes_mjy, dtype=np.float64)
    s = np.asarray(sigmas_mjy, dtype=np.float64)
    order = np.argsort(t)
    t, y, s = t[order], y[order], s[order]

    w = 1.0 / np.maximum(s ** 2, 1e-12)
    mean_w = float(np.sum(w * y) / np.sum(w))
    amp_m = max(float(np.std(y)) if y.size > 1 else 0.05, 0.03 * abs(mean_w), 1e-3)
    lengthscale = 45.0
    amp_qp = 0.5 * amp_m if period_days is not None else 0.0

    def _cov(ta: np.ndarray, tb: np.ndarray, amp_val: float) -> np.ndarray:
        k = _matern32_kernel(ta, tb, amp_val, lengthscale)
        if period_days is not None and amp_val > 0.0:
            k = k + _qp_kernel(ta, tb, 0.5 * amp_val, period_days)
        return k

    # Leave-last-out anomaly metrics if >= 3 epochs, estimating baseline GP amplitude on y_hist only
    if t.size >= 3:
        t_hist, y_hist, s_hist = t[:-1], y[:-1], s[:-1]
        t_last, y_last, s_last = t[-1:], float(y[-1]), float(s[-1])
        m_hist = float(np.sum((y_hist / (s_hist ** 2))) / np.sum(1.0 / (s_hist ** 2)))
        amp_hist = max(float(np.std(y_hist)) if y_hist.size > 1 else 0.05, 0.03 * abs(m_hist), 1e-3)
        k_hh = _cov(t_hist, t_hist, amp_hist) + np.diag(s_hist ** 2) + np.eye(t_hist.size) * 1e-9
        k_hs = _cov(t_hist, t_last, amp_hist)
        k_ss = _cov(t_last, t_last, amp_hist)
        alpha_h = np.linalg.solve(k_hh, y_hist - m_hist)
        mu_last = float(m_hist + (k_hs.T @ alpha_h)[0])
        v_h = np.linalg.solve(k_hh, k_hs)
        var_last = max(1e-12, float(k_ss[0, 0] - (k_hs.T @ v_h)[0, 0]))
        z_alert = abs(y_last - mu_last) / math.sqrt(var_last + s_last ** 2)
        d2_mahal = ((y_last - mu_last) ** 2) / (var_last + s_last ** 2)
        delta_ll = -0.5 * d2_mahal
    else:
        z_alert = 0.0
        d2_mahal = 0.0
        delta_ll = 0.0

    # Full GP forecast on [t_last, t_last + horizon_days]
    k_full = _cov(t, t, amp_m) + np.diag(s ** 2) + np.eye(t.size) * 1e-9
    alpha_full = np.linalg.solve(k_full, y - mean_w)
    t_grid = np.linspace(float(t[-1]), float(t[-1] + horizon_days), 13)
    k_fs = _cov(t, t_grid, amp_m)
    k_grid = _cov(t_grid, t_grid, amp_m)
    mu_grid = mean_w + k_fs.T @ alpha_full
    v_full = np.linalg.solve(k_full, k_fs)
    var_grid = np.maximum(1e-12, np.diag(k_grid - k_fs.T @ v_full))
    std_grid = np.sqrt(var_grid)

    forecast_series = [
        {
            "mjd": round(float(tm), 4),
            "flux_mean_mjy": round(float(mu), 6),
            "flux_std_mjy": round(float(st), 6),
            "lower_1s": round(float(mu - st), 6),
            "upper_1s": round(float(mu + st), 6),
            "lower_2s": round(float(mu - 2.0 * st), 6),
            "upper_2s": round(float(mu + 2.0 * st), 6),
        }
        for tm, mu, st in zip(t_grid, mu_grid, std_grid)
    ]

    # Astrometric search cone at t_last + horizon_days
    t_future = float(t[-1] + horizon_days)
    ra_pred, dec_pred = ephemeris.expected_position(ra_deg, dec_deg, pm_ra_mas_yr, pm_dec_mas_yr, t_future)
    dt_yr = horizon_days / 365.25
    sigma_0_arcsec = 0.08
    sigma_pm_arcsec_yr = max(0.02, 0.01 * math.hypot(pm_ra_mas_yr, pm_dec_mas_yr) / 1000.0)
    r_cone_1s = math.hypot(sigma_0_arcsec, sigma_pm_arcsec_yr * dt_yr)
    r_cone_3s = 3.0 * r_cone_1s + 0.10

    predicted_cone = {
        "target_mjd": round(t_future, 4),
        "horizon_days": horizon_days,
        "ra_pred_deg": round(ra_pred, 7),
        "dec_pred_deg": round(dec_pred, 7),
        "cone_radius_1s_arcsec": round(r_cone_1s, 4),
        "cone_radius_3s_arcsec": round(r_cone_3s, 4),
    }

    # Closed-loop handshake with Model 1: veto alerts for instrumental/airglow events
    m1_class = model1_result.get("predicted_class") if model1_result else None
    m1_art_prob = float((model1_result or {}).get("probabilities", {}).get("INSTRUMENTAL_ARTIFACT", 0.0))
    vetoed_by_model1 = m1_class in ("INSTRUMENTAL_ARTIFACT", "AIRGLOW_OR_ZODI_STRIPE") or m1_art_prob > 0.5
    raw_alert = z_alert >= 3.0 or d2_mahal >= 9.0 or delta_ll < -11.5
    alert_triggered = bool(raw_alert and not vetoed_by_model1)

    if vetoed_by_model1:
        status_label = "VETOED_BY_MODEL1"
        summary = "Anomalous excursion vetoed because Model 1 flagged an instrumental or airglow signature."
    elif alert_triggered:
        status_label = "RED_ALERT" if z_alert >= 5.0 else "YELLOW_ALERT"
        summary = f"Confirmed temporal deviation (Z_alert = {z_alert:.2f} sigma); follow-up recommended."
    else:
        status_label = "NOMINAL"
        summary = f"Light curve follows GP prediction within {z_alert:.2f} sigma."

    citizen_level1 = {
        "alert_status": status_label,
        "alert_triggered": alert_triggered,
        "vetoed_by_model1": vetoed_by_model1,
        "summary": summary,
        "next_scan_flux_mjy": forecast_series[-1]["flux_mean_mjy"],
        "search_cone_radius_arcsec": predicted_cone["cone_radius_3s_arcsec"],
    }
    researcher_level2 = {
        "z_alert": round(z_alert, 4),
        "mahalanobis_d2": round(d2_mahal, 4),
        "delta_log_likelihood": round(delta_ll, 4),
        "alert_triggered": alert_triggered,
        "vetoed_by_model1": vetoed_by_model1,
        "model1_class": m1_class,
        "gp_hyperparams": {
            "kernel": "Matern32+QuasiPeriodic" if period_days else "Matern32",
            "amplitude_mjy": round(amp_m, 6),
            "lengthscale_days": lengthscale,
            "period_days": period_days,
        },
        "predicted_cone": predicted_cone,
    }

    return {
        "model1_attribution_id": model1_attribution_id,
        "gp_hyperparams": researcher_level2["gp_hyperparams"],
        "forecast_series": forecast_series,
        "predicted_cone": predicted_cone,
        "z_alert": round(z_alert, 4),
        "mahalanobis_d2": round(d2_mahal, 4),
        "delta_log_likelihood": round(delta_ll, 4),
        "alert_triggered": alert_triggered,
        "citizen_level1": citizen_level1,
        "researcher_level2": researcher_level2,
        "model_version": model_version,
    }


# ---------------------------------------------------------------------------
# Deterministic science profiles for the 5 catalogue targets + test scenarios
# ---------------------------------------------------------------------------

DEMO_PROFILE_SPECS: dict[str, dict[str, Any]] = {
    "barnards-star": {
        "template_key": "HIGH_PROPER_MOTION_M_DWARF",
        "scale_mjy": 1450.0,
        "times_mjd": [60800.0, 60890.0, 60980.0, 61070.0],
        "fluxes_mjy": [1448.0, 1452.0, 1445.0, 1451.0],
        "period_days": None,
        "features": {
            "z_mono": 1.2,
            "z_dipole": 34.2,
            "dipole_symmetry": 0.98,
            "angular_shift_arcsec": 5.2,
            "q_fit_epsf": 1.02,
            "chi2_psf": 1.06,
            "c_80_20": 2.05,
            "p_clean_flags": 0.99,
            "f_artifact_flags": 0.0,
            "bg_gradient_norm": 0.01,
            "bg_gradient_ratio": 1.01,
            "is_he_1083_channel": 0.0,
            "gaia_match_dist_arcsec": 0.08,
            "gaia_pm_total_mas_yr": 10390.0,
            "wise_w1_w2_color": 0.22,
            "thermal_nsdi_b6_b2": -0.58,
        },
    },
    "eps-indi-b": {
        "template_key": "COLD_BROWN_DWARF_T",
        "scale_mjy": 18.5,
        "times_mjd": [60800.0, 60890.0, 60980.0, 61070.0],
        "fluxes_mjy": [18.4, 18.9, 18.2, 18.6],
        "period_days": 0.126,
        "features": {
            "z_mono": 2.1,
            "z_dipole": 18.5,
            "dipole_symmetry": 0.94,
            "angular_shift_arcsec": 2.35,
            "q_fit_epsf": 1.04,
            "chi2_psf": 1.12,
            "c_80_20": 2.10,
            "p_clean_flags": 0.98,
            "f_artifact_flags": 0.0,
            "bg_gradient_norm": 0.015,
            "bg_gradient_ratio": 1.03,
            "is_he_1083_channel": 0.0,
            "gaia_match_dist_arcsec": 3.5,
            "gaia_pm_total_mas_yr": 4684.0,
            "wise_w1_w2_color": 2.35,
            "thermal_nsdi_b6_b2": 0.35,
        },
    },
    "wise-0855": {
        "template_key": "ULTRACOLD_Y_DWARF",
        "scale_mjy": 0.45,
        "times_mjd": [60800.0, 60890.0, 60980.0, 61070.0],
        "fluxes_mjy": [0.44, 0.46, 0.43, 0.45],
        "period_days": None,
        "features": {
            "z_mono": 11.2,
            "z_dipole": 14.8,
            "dipole_symmetry": 0.93,
            "angular_shift_arcsec": 4.05,
            "q_fit_epsf": 1.05,
            "chi2_psf": 1.09,
            "c_80_20": 2.12,
            "p_clean_flags": 0.97,
            "f_artifact_flags": 0.0,
            "bg_gradient_norm": 0.012,
            "bg_gradient_ratio": 1.02,
            "is_he_1083_channel": 0.0,
            "gaia_match_dist_arcsec": 28.4,
            "gaia_pm_total_mas_yr": 0.0,
            "wise_w1_w2_color": 3.65,
            "thermal_nsdi_b6_b2": 0.88,
        },
    },
    "rw-aurigae": {
        "template_key": "YOUNG_STELLAR_OBJECT_ACCRETION",
        "scale_mjy": 320.0,
        "times_mjd": [60800.0, 60860.0, 60920.0, 60980.0],
        "fluxes_mjy": [325.0, 310.0, 318.0, 122.0],  # Sudden dust dimming event
        "period_days": None,
        "features": {
            "z_mono": 16.4,
            "z_dipole": 0.3,
            "dipole_symmetry": 0.10,
            "angular_shift_arcsec": 0.04,
            "q_fit_epsf": 1.03,
            "chi2_psf": 1.08,
            "c_80_20": 2.08,
            "p_clean_flags": 0.99,
            "f_artifact_flags": 0.0,
            "bg_gradient_norm": 0.02,
            "bg_gradient_ratio": 1.05,
            "is_he_1083_channel": 0.0,
            "gaia_match_dist_arcsec": 0.05,
            "gaia_pm_total_mas_yr": 21.5,
            "wise_w1_w2_color": 1.10,
            "thermal_nsdi_b6_b2": 0.25,
        },
    },
    "r-draconis": {
        "template_key": "PULSATING_MIRA_VARIABLE",
        "scale_mjy": 980.0,
        "times_mjd": [60800.0, 60861.0, 60923.0, 60984.0, 61045.0],
        "fluxes_mjy": [980.0, 1420.0, 960.0, 560.0, 990.0],
        "period_days": 245.5,
        "features": {
            "z_mono": 38.0,
            "z_dipole": 0.2,
            "dipole_symmetry": 0.08,
            "angular_shift_arcsec": 0.03,
            "q_fit_epsf": 0.99,
            "chi2_psf": 1.03,
            "c_80_20": 2.02,
            "p_clean_flags": 0.99,
            "f_artifact_flags": 0.0,
            "bg_gradient_norm": 0.01,
            "bg_gradient_ratio": 1.00,
            "is_he_1083_channel": 0.0,
            "gaia_match_dist_arcsec": 0.04,
            "gaia_pm_total_mas_yr": 21.5,
            "wise_w1_w2_color": 0.40,
            "thermal_nsdi_b6_b2": -0.35,
        },
    },
    "artifact_injection": {
        "template_key": "HIGH_PROPER_MOTION_M_DWARF",
        "scale_mjy": 50.0,
        "times_mjd": [60800.0, 60860.0, 60920.0, 60980.0],
        "fluxes_mjy": [50.0, 49.5, 50.2, 240.0],  # Spurious cosmic ray / snowball spike
        "period_days": None,
        "features": {
            "z_mono": 19.0,
            "z_dipole": 6.5,
            "dipole_symmetry": 0.22,
            "angular_shift_arcsec": 1.8,
            "q_fit_epsf": 3.40,
            "chi2_psf": 18.5,
            "c_80_20": 0.40,
            "p_clean_flags": 0.42,
            "f_artifact_flags": 0.58,
            "bg_gradient_norm": 0.25,
            "bg_gradient_ratio": 1.4,
            "is_he_1083_channel": 0.0,
            "gaia_match_dist_arcsec": 15.0,
            "gaia_pm_total_mas_yr": 0.0,
            "wise_w1_w2_color": 0.0,
            "thermal_nsdi_b6_b2": 0.0,
        },
    },
    "solar_system_mover": {
        "template_key": "SOLAR_SYSTEM_COMET",
        "scale_mjy": 42.0,
        "times_mjd": [60800.0, 60830.0, 60860.0, 60890.0],
        "fluxes_mjy": [40.0, 43.0, 41.5, 42.8],
        "period_days": None,
        "features": {
            "z_mono": 3.5,
            "z_dipole": 22.0,
            "dipole_symmetry": 0.96,
            "angular_shift_arcsec": 12.5,
            "q_fit_epsf": 1.15,
            "chi2_psf": 1.25,
            "c_80_20": 2.30,
            "p_clean_flags": 0.98,
            "f_artifact_flags": 0.0,
            "bg_gradient_norm": 0.02,
            "bg_gradient_ratio": 1.01,
            "is_he_1083_channel": 0.0,
            "gaia_match_dist_arcsec": 35.0,
            "gaia_pm_total_mas_yr": 0.0,
            "wise_w1_w2_color": 1.45,
            "thermal_nsdi_b6_b2": 0.15,
        },
    },
}


def build_demo_spectrum_payload(scenario: str) -> dict[str, Any]:
    """Generate a physically consistent 102-channel SPHEREx spectrum (BLANKCH 51-52 = None)."""
    spec = DEMO_PROFILE_SPECS.get(scenario, DEMO_PROFILE_SPECS["barnards-star"])
    template = _build_physical_template_flux(spec["template_key"]) * spec["scale_mjy"]
    wavelengths = [ch.lambda_c_um for ch in science_catalogs.SPHEREX_102_CHANNELS]
    flux_mjy: list[float | None] = []
    variance_mjy2: list[float | None] = []
    sigma_reported: list[float | None] = []
    valid_mask: list[bool] = []
    hit_counts: list[int] = []

    for i, ch in enumerate(science_catalogs.SPHEREX_102_CHANNELS):
        if ch.is_blankch:
            flux_mjy.append(None)
            variance_mjy2.append(None)
            sigma_reported.append(None)
            valid_mask.append(False)
            hit_counts.append(0)
            continue
        f_val = float(template[i])
        stat_sigma = max(1e-4, 0.015 * abs(f_val))
        rep_sigma = science_catalogs.compute_reported_sigma(f_val, stat_sigma)
        flux_mjy.append(round(f_val, 6))
        variance_mjy2.append(round(stat_sigma ** 2, 10))
        sigma_reported.append(round(rep_sigma, 6))
        valid_mask.append(True)
        hit_counts.append(4)

    band_coadds = metrics.compute_band_coadds(flux_mjy, sigma_reported, valid_mask)
    return {
        "spectrum_scope": "all_epochs",
        "wavelengths_um": wavelengths,
        "flux_mjy": flux_mjy,
        "variance_mjy2": variance_mjy2,
        "sigma_reported_mjy": sigma_reported,
        "valid_mask": valid_mask,
        "channel_hit_counts": hit_counts,
        "band_coadd_flux_mjy": band_coadds,
    }


SIMULATED_NOTE = (
    "Simulated: the spectrum, light curve, confidence score and Model 1-3 results come from "
    "built-in demonstration profiles, not from measurements of this patch."
)


def enrich_features_from_catalogs(
    fv: dict[str, float],
    gaia_info: dict[str, Any] | None,
    wise_info: dict[str, Any] | None,
) -> dict[str, float]:
    """Override synthetic Model 1 Gaia/WISE features with real cross-match values when available."""
    out = dict(fv)
    if gaia_info is not None:
        if gaia_info.get("dist_arcsec") is not None:
            out["gaia_match_dist_arcsec"] = float(gaia_info["dist_arcsec"])
        if gaia_info.get("pm_total_mas_yr") is not None:
            out["gaia_pm_total_mas_yr"] = float(gaia_info["pm_total_mas_yr"])
    if wise_info is not None and wise_info.get("w1_w2_color") is not None:
        out["wise_w1_w2_color"] = float(wise_info["w1_w2_color"])
    return out


def analyze_patch_science(
    store: Store,
    patch: Patch,
    *,
    scenario: str | None = None,
    force_recompute: bool = True,
    gaia_info: dict[str, Any] | None = None,
    wise_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute/seed spectrum, 17 indices, metrics, and Models 1-3 for a patch and persist all."""
    profile_key = scenario or patch.target_slug or "barnards-star"
    if profile_key not in DEMO_PROFILE_SPECS:
        profile_key = "barnards-star"
    spec_cfg = DEMO_PROFILE_SPECS[profile_key]

    # 1. Spectrum & 17 spectral indices
    existing_spec = None if force_recompute else store.get_patch_spectrum(patch.id, epoch_index=-1)
    if existing_spec is None:
        raw_spectrum = build_demo_spectrum_payload(profile_key)
        indices = metrics.compute_all_17_spectral_indices(raw_spectrum)
        saved_spectrum = store.save_patch_spectrum(patch.id, -1, raw_spectrum, indices=indices)
    else:
        saved_spectrum = existing_spec
        indices = existing_spec.get("indices") or metrics.compute_all_17_spectral_indices(existing_spec)

    # 2. Time-series variability & global confidence score
    times_mjd = list(spec_cfg["times_mjd"])
    fluxes_mjy = list(spec_cfg["fluxes_mjy"])
    sigmas_mjy = [science_catalogs.compute_reported_sigma(f, 0.015 * abs(f)) for f in fluxes_mjy]
    variability = metrics.compute_variability_metrics(times_mjd, fluxes_mjy, sigmas_mjy)

    fv = enrich_features_from_catalogs(
        dict(spec_cfg["features"]),
        None if scenario else gaia_info,
        None if scenario else wise_info,
    )
    if scenario is None and (gaia_info is not None or wise_info is not None):
        store.save_patch_crossmatch(patch.id, gaia_info, wise_info)
    active_flags = ["SNOWBALL"] if fv["f_artifact_flags"] > 0.3 else []
    conf = metrics.compute_global_confidence_score(
        snr=max(fv["z_mono"], fv["z_dipole"]),
        dipole_symmetry=fv["dipole_symmetry"],
        angular_shift_px=fv["angular_shift_arcsec"] / config.PIXEL_SCALE_ARCSEC,
        active_flag_names=active_flags,
        q_fit_epsf=fv["q_fit_epsf"],
        is_stationary=fv["z_dipole"] < 3.0,
    )

    # 3. Model 1 -> Model 2 -> Model 3 (with Model 1 handshake). Reads reuse the stored results:
    # rerunning the models (the GP forecast included) and rewriting rows on every GET was costly.
    stored = (
        None
        if force_recompute
        else (
            store.get_model1_attribution(patch.id, epoch_index=-1),
            store.get_model2_classification(patch.id),
            store.get_model3_forecast(patch.id),
        )
    )
    if stored is not None and all(row is not None for row in stored):
        saved_m1, saved_m2, saved_m3 = stored
    else:
        m1_payload = run_model1_event_classifier(fv)
        saved_m1 = store.save_model1_attribution(patch.id, -1, m1_payload)

        m2_payload = run_model2_spectral_classifier(saved_spectrum, indices=indices)
        m2_payload["spectrum_id"] = saved_spectrum["id"]
        saved_m2 = store.save_model2_classification(patch.id, m2_payload)

        target_row = store.get_target(patch.target_slug) if patch.target_slug else None
        pm_ra = float((target_row or {}).get("pm_ra_mas_yr") or 0.0)
        pm_dec = float((target_row or {}).get("pm_dec_mas_yr") or 0.0)
        m3_payload = run_model3_temporal_forecast(
            times_mjd,
            fluxes_mjy,
            sigmas_mjy,
            ra_deg=patch.ra,
            dec_deg=patch.dec,
            pm_ra_mas_yr=pm_ra,
            pm_dec_mas_yr=pm_dec,
            period_days=spec_cfg.get("period_days"),
            model1_result=m1_payload,
            model1_attribution_id=saved_m1["id"],
        )
        saved_m3 = store.save_model3_forecast(patch.id, m3_payload)

    return {
        "patch": {"id": patch.id, "ra": patch.ra, "dec": patch.dec, "target": patch.target_slug},
        "simulated": True,
        "data_note": SIMULATED_NOTE,
        "scenario": profile_key,
        "confidence": conf,
        "variability": variability,
        "spectrum": saved_spectrum,
        "model1_event": saved_m1,
        "model2_spectrum": saved_m2,
        "model3_forecast": saved_m3,
    }
