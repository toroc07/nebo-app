"""Master SPHEREx scientific constants, 102 spectral channels, and 17 spectral indices.

Grounded in METRICAS_Y_MODELOS.md (Tables 1.2, 2.5, bitmasks, and Golden Rules):
- Bitmasks: MASK_BACKGROUND = 0x3E2ACEC7, MASK_PHOTOMETRY = 0x3C02CEC4
- Dichroic blind spots (BLANKCH): global channels 51 and 52 must NEVER be imputed as 0.0
- Minimum systematic error floor: sigma_reported^2 = sigma_stat^2 + (0.03 * flux)^2
"""

from __future__ import annotations

from dataclasses import dataclass
import math

MASK_BACKGROUND: int = 0x3E2ACEC7
MASK_PHOTOMETRY: int = 0x3C02CEC4
BLANK_CHANNELS: tuple[int, ...] = (51, 52)
SYSTEMATIC_ERROR_FLOOR: float = 0.03


@dataclass(frozen=True)
class SpherexChannelSpec:
    channel_id: int
    band: int
    detector_channel: int
    lambda_c_um: float
    lambda_min_um: float
    lambda_max_um: float
    resolving_power_r: float
    resolving_power_unc: float
    is_blankch: bool
    tracer_description: str


@dataclass(frozen=True)
class SpectralIndexSpec:
    index_id: int
    index_code: str
    target_physics: str
    formula_type: str
    feature_channels: tuple[int, ...]
    blue_anchor_channel: int | None
    red_anchor_channel: int | None
    band_a: int | None
    band_b: int | None
    discriminator_note: str


_RAW_CHANNELS: tuple[tuple[int, int, int, float, float, float, float, float, bool, str], ...] = (
    # Band 1 (Channels 1-17)
    (1, 1, 1, 0.753, 0.743, 0.762, 42.0, 1.1, False, "Continuo óptico / Ancla de caída Rayleigh-Jeans"),
    (2, 1, 2, 0.771, 0.761, 0.781, 42.0, 1.0, False, "Doblete neutro K I (0.7665 / 0.7699 µm) en enanas rojas"),
    (3, 1, 3, 0.790, 0.780, 0.800, 41.0, 0.9, False, "Airglow atmosférico OH de mesosfera terrestre"),
    (4, 1, 4, 0.809, 0.798, 0.819, 40.0, 0.9, False, "Continuo cercano al infrarrojo"),
    (5, 1, 5, 0.828, 0.817, 0.839, 40.0, 0.8, False, "Continuo del límite de la serie de Paschen"),
    (6, 1, 6, 0.848, 0.837, 0.859, 40.0, 0.8, False, "Triplete de Ca II (0.8498, 0.8542 µm)"),
    (7, 1, 7, 0.868, 0.857, 0.879, 40.0, 0.7, False, "Triplete de Ca II (0.8662 µm)"),
    (8, 1, 8, 0.889, 0.877, 0.900, 39.0, 0.7, False, "Serie de Paschen de hidrógeno"),
    (9, 1, 9, 0.910, 0.898, 0.922, 39.0, 0.6, False, "Continuo estelar en el infrarrojo cercano"),
    (10, 1, 10, 0.932, 0.920, 0.944, 39.0, 0.6, False, "Absorción de H2O telúrica / interestelar"),
    (11, 1, 11, 0.955, 0.942, 0.967, 39.0, 0.5, False, "Línea de recombinación Pa-epsilon (0.9546 µm)"),
    (12, 1, 12, 0.978, 0.964, 0.990, 38.0, 0.5, False, "Banda Wing-Ford de FeH (0.99 µm en enanas L y T)"),
    (13, 1, 13, 1.001, 0.988, 1.014, 38.0, 0.5, False, "Línea Pa-delta (1.0049 µm)"),
    (14, 1, 14, 1.025, 1.011, 1.039, 38.0, 0.5, False, "Banda de FeH en enanas T tempranas"),
    (15, 1, 15, 1.050, 1.036, 1.064, 38.0, 0.5, False, "Pico fotométrico de banda Y en objetos fríos"),
    (16, 1, 16, 1.075, 1.061, 1.090, 37.0, 0.4, False, "Ala azul de la línea atmosférica de He I (1.083 µm)"),
    (17, 1, 17, 1.102, 1.086, 1.116, 37.0, 0.4, False, "Línea de Airglow de He I metaestable (1.0830 µm)"),
    # Band 2 (Channels 18-34)
    (18, 2, 1, 1.113, 1.099, 1.126, 43.0, 0.7, False, "Transición de Detector 1 a 2 / Fuga de He I"),
    (19, 2, 2, 1.139, 1.124, 1.153, 42.0, 0.6, False, "Inicio de absorción molecular de H2O"),
    (20, 2, 3, 1.167, 1.152, 1.182, 42.0, 0.5, False, "Continuo interbanda 1.1 – 1.2 µm"),
    (21, 2, 4, 1.195, 1.180, 1.210, 41.0, 0.5, False, "Óxido de vanadio (VO) y FeH en enanas marrones"),
    (22, 2, 5, 1.224, 1.209, 1.240, 41.0, 0.5, False, "Pseudocontinuo de banda J"),
    (23, 2, 6, 1.254, 1.238, 1.269, 41.0, 0.4, False, "Pico de flujo en banda J"),
    (24, 2, 7, 1.284, 1.267, 1.300, 42.0, 0.4, False, "Paschen-beta (Pa-beta, 1.2818 µm) en acreción"),
    (25, 2, 8, 1.315, 1.298, 1.331, 42.0, 0.4, False, "Continuo azul previo a la banda de agua de 1.4 µm"),
    (26, 2, 9, 1.346, 1.329, 1.363, 42.0, 0.4, False, "Ala de absorción de H2O vapor"),
    (27, 2, 10, 1.378, 1.360, 1.396, 42.0, 0.4, False, "Borde de absorción profunda de H2O"),
    (28, 2, 11, 1.412, 1.393, 1.430, 41.0, 0.4, False, "Mínimo de absorción de H2O vapor (1.4 µm)"),
    (29, 2, 12, 1.446, 1.426, 1.464, 41.0, 0.3, False, "Banda de H2O en enanas M y T"),
    (30, 2, 13, 1.481, 1.461, 1.500, 41.0, 0.3, False, "Recuperación de flujo hacia banda H"),
    (31, 2, 14, 1.517, 1.496, 1.537, 41.0, 0.3, False, "Canal de ancla de continuo de referencia"),
    (32, 2, 15, 1.554, 1.533, 1.575, 41.0, 0.3, False, "Pico de flujo en banda H para objetos fríos"),
    (33, 2, 16, 1.592, 1.570, 1.613, 41.0, 0.3, False, "Pico H / Referencia de continuo de metano"),
    (34, 2, 17, 1.631, 1.608, 1.651, 41.0, 0.3, False, "Transición de Detector 2 a Detector 3"),
    # Band 3 (Channels 35-51)
    (35, 3, 1, 1.656, 1.636, 1.676, 42.0, 0.3, False, "Sobretono 2nu3 de Metano CH4 (1.66 µm)"),
    (36, 3, 2, 1.695, 1.675, 1.715, 42.0, 0.3, False, "Pendiente de absorción de CH4 en enanas T/Y"),
    (37, 3, 3, 1.735, 1.714, 1.756, 41.0, 0.3, False, "Ala roja de la banda H"),
    (38, 3, 4, 1.775, 1.754, 1.797, 41.0, 0.3, False, "Ancla azul de continuo para agua a 1.9 µm"),
    (39, 3, 5, 1.818, 1.795, 1.840, 41.0, 0.3, False, "Ala de absorción de vapor de H2O"),
    (40, 3, 6, 1.861, 1.838, 1.884, 41.0, 0.3, False, "Paschen-alpha (Pa-alpha, 1.8756 µm)"),
    (41, 3, 7, 1.905, 1.881, 1.928, 41.0, 0.3, False, "Mínimo de absorción de H2O vapor (1.9 µm)"),
    (42, 3, 8, 1.949, 1.925, 1.973, 41.0, 0.3, False, "Ala roja de absorción de H2O"),
    (43, 3, 9, 1.995, 1.970, 2.019, 41.0, 0.3, False, "Inicio de continuo en banda K"),
    (44, 3, 10, 2.041, 2.015, 2.067, 40.0, 0.4, False, "Pico de banda K (lado azul)"),
    (45, 3, 11, 2.089, 2.062, 2.115, 40.0, 0.3, False, "Ancla de continuo libre de líneas"),
    (46, 3, 12, 2.139, 2.111, 2.165, 40.0, 0.3, False, "H2 1-0 S(1) (2.1218 µm) y Br-gamma (2.166 µm)"),
    (47, 3, 13, 2.189, 2.160, 2.216, 40.0, 0.3, False, "Pico de emisión en banda K"),
    (48, 3, 14, 2.240, 2.211, 2.268, 40.0, 0.3, False, "Metano CH4 nu2+nu3 (2.20 - 2.24 µm)"),
    (49, 3, 15, 2.292, 2.262, 2.321, 40.0, 0.3, False, "Sobretono de CO (2-0, 2.2935 µm) en gigantes"),
    (50, 3, 16, 2.345, 2.314, 2.375, 40.0, 0.3, False, "Sobretono de CO (3-1 2.322 µm, 4-2 2.352 µm)"),
    (51, 3, 17, 2.399, 2.367, 2.421, 41.0, 4.0, True, "BLANKCH (NaN en DR1) — Borde Dicroico SWIR"),
    # Band 4 (Channels 52-68)
    (52, 4, 1, 2.445, 2.422, 2.474, 42.0, 7.6, True, "BLANKCH (NaN en DR1) — Borde Dicroico MWIR"),
    (53, 4, 2, 2.506, 2.470, 2.542, 34.0, 0.4, False, "Inicio de continuo en infrarrojo medio"),
    (54, 4, 3, 2.575, 2.538, 2.612, 35.0, 0.5, False, "Ventana de transmisión interbanda"),
    (55, 4, 4, 2.646, 2.607, 2.684, 35.0, 0.5, False, "Comienzo de absorción de H2O vapor"),
    (56, 4, 5, 2.719, 2.678, 2.758, 35.0, 0.6, False, "Mínimo de absorción de H2O vapor (2.7 µm)"),
    (57, 4, 6, 2.794, 2.752, 2.835, 35.0, 0.8, False, "Ancla azul de continuo para hielo de H2O"),
    (58, 4, 7, 2.871, 2.828, 2.914, 34.0, 0.6, False, "Pendiente de absorción de hielo"),
    (59, 4, 8, 2.951, 2.906, 2.995, 34.0, 0.6, False, "Ala de absorción de hielo de H2O sólido"),
    (60, 4, 9, 3.033, 2.985, 3.079, 34.0, 0.6, False, "Máxima absorción de Hielo de H2O (3.05 µm)"),
    (61, 4, 10, 3.118, 3.069, 3.164, 34.0, 0.6, False, "Recuperación de absorción de hielo de H2O"),
    (62, 4, 11, 3.204, 3.155, 3.252, 35.0, 0.5, False, "Componente de hidrato de amoníaco (NH3) sólido"),
    (63, 4, 12, 3.293, 3.242, 3.342, 35.0, 0.5, False, "CH4 fundamental nu3 (3.3 µm) y PAH 3.3 µm"),
    (64, 4, 13, 3.383, 3.330, 3.434, 35.0, 0.6, False, "Mínimo de absorción de CH4 en enanas T/Y"),
    (65, 4, 14, 3.476, 3.422, 3.528, 36.0, 0.6, False, "Estiramiento alifático C-H (3.4 µm)"),
    (66, 4, 15, 3.570, 3.514, 3.624, 36.0, 0.6, False, "Hielo de metanol (CH3OH) a 3.53 µm"),
    (67, 4, 16, 3.667, 3.610, 3.723, 36.0, 0.8, False, "Ancla roja de continuo para complejo de 3.0 µm"),
    (68, 4, 17, 3.768, 3.707, 3.827, 36.0, 0.9, False, "Transición de Detector 4 a Detector 5"),
    # Band 5 (Channels 69-85)
    (69, 5, 1, 3.834, 3.815, 3.852, 109.0, 0.4, False, "Inicio de alta resolución (R ~ 110)"),
    (70, 5, 2, 3.867, 3.849, 3.885, 109.0, 0.6, False, "Continuo de alta resolución"),
    (71, 5, 3, 3.901, 3.882, 3.919, 109.0, 0.4, False, "Continuo estelar libre de líneas"),
    (72, 5, 4, 3.936, 3.916, 3.954, 109.0, 0.5, False, "Continuo de alta resolución"),
    (73, 5, 5, 3.970, 3.951, 3.989, 109.0, 0.5, False, "Ancla azul de continuo para Brackett-alpha"),
    (74, 5, 6, 4.005, 3.986, 4.024, 110.0, 0.6, False, "Canal de emisión atmosférica de fondo (4.03 µm)"),
    (75, 5, 7, 4.041, 4.020, 4.059, 110.0, 0.6, False, "Brackett-alpha (Br-alpha, 4.0523 µm) en acreción"),
    (76, 5, 8, 4.076, 4.056, 4.095, 111.0, 0.7, False, "Ancla roja de continuo para Brackett-alpha"),
    (77, 5, 9, 4.112, 4.091, 4.131, 112.0, 0.6, False, "Continuo de alta resolución"),
    (78, 5, 10, 4.148, 4.127, 4.167, 113.0, 0.6, False, "Ancla azul de continuo para banda de CO2"),
    (79, 5, 11, 4.184, 4.163, 4.204, 113.0, 0.6, False, "Comienzo de ala de absorción de CO2"),
    (80, 5, 12, 4.221, 4.199, 4.240, 115.0, 1.1, False, "Ala de hielo de CO2 sólido (4.22 µm)"),
    (81, 5, 13, 4.257, 4.235, 4.277, 114.0, 0.9, False, "CO2 fundamental nu3 asimétrico (4.26 µm)"),
    (82, 5, 14, 4.294, 4.272, 4.314, 115.0, 0.8, False, "Núcleo de banda de CO2 gas y hielo (4.27 µm)"),
    (83, 5, 15, 4.331, 4.308, 4.351, 116.0, 0.9, False, "Recuperación de absorción de CO2"),
    (84, 5, 16, 4.368, 4.345, 4.388, 116.0, 1.0, False, "Ancla roja de continuo para CO2"),
    (85, 5, 17, 4.405, 4.382, 4.427, 117.0, 1.2, False, "Transición de Detector 5 a Detector 6"),
    # Band 6 (Channels 86-102)
    (86, 6, 1, 4.435, 4.418, 4.452, 129.0, 1.6, False, "Máxima resolución espectral (R ≈ 129)"),
    (87, 6, 2, 4.468, 4.450, 4.485, 125.0, 1.1, False, "Continuo de alta resolución"),
    (88, 6, 3, 4.500, 4.483, 4.518, 127.0, 1.2, False, "Continuo de alta resolución"),
    (89, 6, 4, 4.533, 4.515, 4.551, 126.0, 1.2, False, "Continuo estelar"),
    (90, 6, 5, 4.567, 4.548, 4.585, 127.0, 1.3, False, "Ancla azul de continuo para monóxido de carbono"),
    (91, 6, 6, 4.601, 4.582, 4.619, 126.0, 1.4, False, "Inicio de rama fundamental 1-0 de CO"),
    (92, 6, 7, 4.635, 4.616, 4.653, 127.0, 1.4, False, "Hielo de monóxido de carbono (CO ice, 4.65 µm)"),
    (93, 6, 8, 4.669, 4.650, 4.688, 126.0, 1.7, False, "Banda fundamental de CO (4.67 µm, rama P/R)"),
    (94, 6, 9, 4.704, 4.684, 4.723, 128.0, 1.9, False, "Pico de rama R de banda fundamental de CO"),
    (95, 6, 10, 4.739, 4.719, 4.758, 130.0, 3.4, False, "Ala roja de absorción de CO"),
    (96, 6, 11, 4.774, 4.753, 4.793, 131.0, 2.4, False, "Ancla roja de continuo para CO"),
    (97, 6, 12, 4.808, 4.788, 4.827, 132.0, 2.6, False, "Continuo térmico para fuentes subestelares frías"),
    (98, 6, 13, 4.843, 4.823, 4.863, 131.0, 2.3, False, "Pico de emisión térmica para objetos con T ~ 250 K"),
    (99, 6, 14, 4.879, 4.858, 4.899, 130.0, 2.5, False, "Emisión térmica infrarroja"),
    (100, 6, 15, 4.915, 4.894, 4.936, 131.0, 2.8, False, "Emisión térmica infrarroja"),
    (101, 6, 16, 4.952, 4.930, 4.973, 132.0, 3.0, False, "Canal del extremo rojo de relevamiento"),
    (102, 6, 17, 4.989, 4.966, 5.009, 135.0, 4.3, False, "Límite instrumental de longitud de onda (5.01 µm)"),
)

SPHEREX_102_CHANNELS: tuple[SpherexChannelSpec, ...] = tuple(
    SpherexChannelSpec(*row) for row in _RAW_CHANNELS
)

CHANNELS_BY_ID: dict[int, SpherexChannelSpec] = {
    ch.channel_id: ch for ch in SPHEREX_102_CHANNELS
}

_RAW_INDICES: tuple[
    tuple[int, str, str, str, tuple[int, ...], int | None, int | None, int | None, int | None, str],
    ...,
] = (
    (1, "IND_H2O_14", "Vapor de H2O en enanas M/L/T", "DEPTH_D", (28,), 25, 32, None, None, "Separa enanas rojas de sub-tipos fríos L y T."),
    (2, "IND_H2O_19", "Banda de absorción de agua profunda", "DEPTH_D", (41,), 38, 44, None, None, "Mínimo característico en enanas T y gigantes Mira."),
    (3, "IND_H2O_ICE", "Hielo de agua en discos y cometas", "EQUIV_WIDTH_W", (59, 60, 61, 62), 57, 67, None, None, "Diagnostica mantos de hielo en polvo, cometas y WISE 0855."),
    (4, "IND_CH4_16", "Metano sobretono en enanas T", "DEPTH_D", (35,), 33, 37, None, None, "Emerge en la transición L -> T (T_eff <= 1400 K)."),
    (5, "IND_CH4_22", "Metano nu2+nu3 en banda K", "DEPTH_D", (48,), 45, 50, None, None, "Deprime el flujo de banda K en enanas T y Y frías."),
    (6, "IND_CH4_33", "Metano fundamental nu3 profundo", "DEPTH_D", (63,), 58, 66, None, None, "La firma molecular dominante de atmósferas con T < 800 K."),
    (7, "IND_CO_23", "Monóxido de carbono sobretono (2-0)", "BLUE_EXTRAP_RATIO", (49, 50), 45, 47, None, None, "Intenso en gigantes rojas AGB (R Dra) y ausente en enanas; Ch47 usado en extrapolación azul por BLANKCH 51-52."),
    (8, "IND_CO_46", "Fundamental de CO (1-0)", "LINE_FLUX_DELTA_F", (93,), 90, 96, None, None, "Resuelto a R ~ 126; gas circumestelar y desequilibrio químico."),
    (9, "IND_CO2_42", "Dióxido de carbono gas y hielo", "DEPTH_D", (81, 82), 78, 84, None, None, "Firma nítida a R ~ 115; cometas activos e hielos prebióticos."),
    (10, "IND_ICE_CO", "Hielo de CO puro ultracongelado", "DEPTH_D", (92,), 90, 95, None, None, "Hielos ultra-volátiles (T_sub ~ 20 K) en nubes moleculares."),
    (11, "IND_PAH_33", "Emisión aromática PAH a 3.3 µm", "LINE_FLUX_DELTA_F", (63,), 61, 65, None, None, "Radiación ultravioleta en regiones de fotodisociación (PDR)."),
    (12, "IND_BR_ALPHA", "Línea Brackett-alpha de hidrógeno", "LINE_FLUX_DELTA_F", (75,), 73, 76, None, None, "Tasa de acreción en objetos estelares jóvenes (RW Aurigae)."),
    (13, "IND_PA_BETA", "Línea Paschen-beta de hidrógeno", "LINE_FLUX_DELTA_F", (24,), 23, 25, None, None, "Indicador de choque de acreción resistente a la extinción."),
    (14, "IND_H2_212", "Hidrógeno molecular H2 1-0 S(1)", "LINE_FLUX_DELTA_F", (46,), 45, 47, None, None, "Trazador de choques en vientos protostelares y discos."),
    (15, "IND_HE_AIRGLOW", "Línea de He I metaestable 1.083 µm", "LINE_FLUX_DELTA_F", (17,), 15, 18, None, None, "Veto instrumental: discrimina airglow en Banda 1 de fuentes reales."),
    (16, "COLOR_PLANET_X", "Índice térmico ultra-frío", "NSDI", (), None, None, 6, 2, "Aísla enanas marrones frías y Planeta X: valor > +0.70."),
    (17, "COLOR_YSO_DUST", "Exceso infrarrojo por polvo cálido", "COLOR_RATIO", (), None, None, 5, 3, "Diagnostica discos protoplanetarios y de escombros (RW Aur)."),
)

SPHEREX_17_INDICES: tuple[SpectralIndexSpec, ...] = tuple(
    SpectralIndexSpec(*row) for row in _RAW_INDICES
)

INDICES_BY_CODE: dict[str, SpectralIndexSpec] = {
    idx.index_code: idx for idx in SPHEREX_17_INDICES
}


def channel_for_wavelength(detector: int, wavelength_um: float | None) -> int | None:
    """Resolve an observed wavelength (micrometers) on a detector (1..6) to global channel 1..102."""
    if wavelength_um is None or not math.isfinite(wavelength_um) or wavelength_um <= 0.0:
        return None
    band_channels = [ch for ch in SPHEREX_102_CHANNELS if ch.band == detector]
    if not band_channels:
        return None
    for ch in band_channels:
        if ch.lambda_min_um <= wavelength_um <= ch.lambda_max_um:
            return ch.channel_id
    nearest = min(band_channels, key=lambda ch: abs(ch.lambda_c_um - wavelength_um))
    if abs(nearest.lambda_c_um - wavelength_um) <= 0.12:
        return nearest.channel_id
    return None


def compute_reported_sigma(flux: float, stat_sigma: float) -> float:
    """Enforce the SPHEREx 3% systematic floor (Eq. 19): sqrt(sigma_stat^2 + (0.03 * |flux|)^2)."""
    if not (math.isfinite(flux) and math.isfinite(stat_sigma)):
        return float("nan")
    return math.hypot(abs(stat_sigma), SYSTEMATIC_ERROR_FLOOR * abs(flux))


def compute_nsdi(
    flux_band_a: float,
    sigma_band_a: float,
    flux_band_b: float,
    sigma_band_b: float,
) -> tuple[float | None, float | None]:
    """Compute Normalized Spectral Difference Index (F_A - F_B) / (F_A + F_B) and analytical sigma."""
    values = (flux_band_a, sigma_band_a, flux_band_b, sigma_band_b)
    if not all(math.isfinite(v) for v in values):
        return None, None
    denom = flux_band_a + flux_band_b
    if denom <= 0.0:
        return None, None
    nsdi = (flux_band_a - flux_band_b) / denom
    sigma_nsdi = (2.0 / (denom * denom)) * math.hypot(
        flux_band_b * abs(sigma_band_a),
        flux_band_a * abs(sigma_band_b),
    )
    return nsdi, sigma_nsdi


def compute_color_ratio(
    flux_band_a: float,
    sigma_band_a: float,
    flux_band_b: float,
    sigma_band_b: float,
) -> tuple[float | None, float | None]:
    """Compute inter-band flux ratio F_A / F_B and analytical uncertainty."""
    values = (flux_band_a, sigma_band_a, flux_band_b, sigma_band_b)
    if not all(math.isfinite(v) for v in values):
        return None, None
    if flux_band_b == 0.0:
        return None, None
    ratio = flux_band_a / flux_band_b
    rel_a = (abs(sigma_band_a) / abs(flux_band_a)) if flux_band_a != 0.0 else 0.0
    rel_b = abs(sigma_band_b) / abs(flux_band_b)
    sigma_ratio = abs(ratio) * math.hypot(rel_a, rel_b)
    return ratio, sigma_ratio
