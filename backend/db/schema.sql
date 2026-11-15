-- Nebo database schema (PostgreSQL 14+).
-- Safe to run more than once: every statement is idempotent.
-- Apply with:  python -m app.db init   (or psql "$DATABASE_URL" -f db/schema.sql)

-- Catalogue objects shown as markers in the planetarium.
CREATE TABLE IF NOT EXISTS targets (
    slug                  text PRIMARY KEY,
    name                  text NOT NULL,
    ra                    double precision NOT NULL CHECK (ra >= 0 AND ra < 360),
    dec                   double precision NOT NULL CHECK (dec BETWEEN -90 AND 90),
    kind                  text NOT NULL,
    note                  text NOT NULL DEFAULT '',
    pm_ra_mas_yr          double precision,
    pm_dec_mas_yr         double precision,
    recommended_detector  smallint NOT NULL CHECK (recommended_detector BETWEEN 1 AND 6),
    created_at            timestamptz NOT NULL DEFAULT now()
);

-- A position on the sky whose timelines have been (or are being) built.
-- Requests within a few arcseconds of an existing patch reuse it.
CREATE TABLE IF NOT EXISTS patches (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ra           double precision NOT NULL CHECK (ra >= 0 AND ra < 360),
    dec          double precision NOT NULL CHECK (dec BETWEEN -90 AND 90),
    target_slug  text REFERENCES targets (slug) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS patches_dec_idx ON patches (dec);
CREATE INDEX IF NOT EXISTS patches_target_idx ON patches (target_slug);

-- The image timeline of one patch seen by one SPHEREx detector (1-6).
-- status/stage/progress are updated while the backend downloads from IRSA.
CREATE TABLE IF NOT EXISTS timelines (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id        bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    detector        smallint NOT NULL CHECK (detector BETWEEN 1 AND 6),
    status          text NOT NULL CHECK (status IN ('building', 'ready', 'failed')),
    stage           text NOT NULL DEFAULT 'queued',
    progress_done   integer NOT NULL DEFAULT 0,
    progress_total  integer NOT NULL DEFAULT 0,
    error           text,
    frames_found    integer,
    frames_used     integer,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patch_id, detector)
);

-- Every failed IRSA query and every failed build, with its cause (for diagnosing slow fields).
CREATE TABLE IF NOT EXISTS timeline_build_attempts (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    timeline_id bigint NOT NULL REFERENCES timelines (id) ON DELETE CASCADE,
    attempt     integer NOT NULL,
    stage       text NOT NULL,
    cause       text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS timeline_build_attempts_timeline_idx
    ON timeline_build_attempts (timeline_id);

-- One processed PNG per timeline, epoch (~6-month survey pass) and display size.
CREATE TABLE IF NOT EXISTS timeline_images (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    timeline_id       bigint NOT NULL REFERENCES timelines (id) ON DELETE CASCADE,
    epoch_index       smallint NOT NULL,
    size              text NOT NULL CHECK (size IN ('small', 'medium', 'large')),
    start_utc         timestamptz NOT NULL,
    end_utc           timestamptz NOT NULL,
    mid_mjd           double precision NOT NULL,
    frames_available  integer NOT NULL,
    frames_used       integer NOT NULL,
    width_px          integer NOT NULL,
    height_px         integer NOT NULL,
    display_min       double precision NOT NULL,
    display_max       double precision NOT NULL,
    png               bytea NOT NULL,
    npz               bytea,
    gcs_uri           text,
    UNIQUE (timeline_id, epoch_index, size)
);

-- Idempotent column extensions for already-provisioned databases.
ALTER TABLE targets
    ADD COLUMN IF NOT EXISTS gaia_source_id text,
    ADD COLUMN IF NOT EXISTS gaia_dist_arcsec double precision,
    ADD COLUMN IF NOT EXISTS gaia_g_mag double precision,
    ADD COLUMN IF NOT EXISTS wise_w1_mag double precision,
    ADD COLUMN IF NOT EXISTS wise_w2_mag double precision,
    ADD COLUMN IF NOT EXISTS wise_w1_w2_color double precision,
    ADD COLUMN IF NOT EXISTS expected_spectral_class text;

ALTER TABLE patches
    ADD COLUMN IF NOT EXISTS fetch_size_deg double precision,
    ADD COLUMN IF NOT EXISTS pixel_scale_arcsec double precision,
    ADD COLUMN IF NOT EXISTS ra_min_deg double precision,
    ADD COLUMN IF NOT EXISTS ra_max_deg double precision,
    ADD COLUMN IF NOT EXISTS dec_min_deg double precision,
    ADD COLUMN IF NOT EXISTS dec_max_deg double precision,
    ADD COLUMN IF NOT EXISTS sector_corners_json jsonb,
    ADD COLUMN IF NOT EXISTS c_global_confidence double precision,
    ADD COLUMN IF NOT EXISTS gaia_crossmatch_json jsonb,
    ADD COLUMN IF NOT EXISTS wise_crossmatch_json jsonb;

ALTER TABLE timeline_images
    ADD COLUMN IF NOT EXISTS npz bytea,
    ADD COLUMN IF NOT EXISTS gcs_uri text;

-- Exact sky-sector coordinates per patch and display/fetch size (small, medium, large, fetch).
CREATE TABLE IF NOT EXISTS sector_coordinates (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id               bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    size_name              text NOT NULL CHECK (size_name IN ('small', 'medium', 'large', 'fetch')),
    center_ra_deg          double precision NOT NULL,
    center_dec_deg         double precision NOT NULL,
    side_deg               double precision NOT NULL,
    pixel_scale_arcsec     double precision NOT NULL DEFAULT 6.15,
    width_px               integer NOT NULL,
    height_px              integer NOT NULL,
    ra_min_deg             double precision NOT NULL,
    ra_max_deg             double precision NOT NULL,
    dec_min_deg            double precision NOT NULL,
    dec_max_deg            double precision NOT NULL,
    corner_nw_ra           double precision NOT NULL,
    corner_nw_dec          double precision NOT NULL,
    corner_ne_ra           double precision NOT NULL,
    corner_ne_dec          double precision NOT NULL,
    corner_se_ra           double precision NOT NULL,
    corner_se_dec          double precision NOT NULL,
    corner_sw_ra           double precision NOT NULL,
    corner_sw_dec          double precision NOT NULL,
    corners_icrs           jsonb NOT NULL,
    footprint_polygon_text text NOT NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patch_id, size_name)
);

CREATE INDEX IF NOT EXISTS idx_sector_coordinates_patch
    ON sector_coordinates (patch_id);

-- Master catalog of SPHEREx 102 spectral channels (Table 1.2 of METRICAS_Y_MODELOS.md).
-- Channels 51 and 52 are BLANKCH dichroic blind spots and stay NaN/NULL (never imputed as 0).
CREATE TABLE IF NOT EXISTS spherex_channels (
    channel_id          smallint PRIMARY KEY CHECK (channel_id BETWEEN 1 AND 102),
    band                smallint NOT NULL CHECK (band BETWEEN 1 AND 6),
    detector_channel    smallint NOT NULL CHECK (detector_channel BETWEEN 1 AND 17),
    lambda_c_um         double precision NOT NULL,
    lambda_min_um       double precision NOT NULL,
    lambda_max_um       double precision NOT NULL,
    resolving_power_r   double precision NOT NULL,
    resolving_power_unc double precision NOT NULL,
    is_blankch          boolean NOT NULL DEFAULT FALSE,
    tracer_description  text NOT NULL,
    UNIQUE (band, detector_channel)
);

-- Master catalog of 17 diagnostic spectral indices (Table 2.5 of METRICAS_Y_MODELOS.md).
CREATE TABLE IF NOT EXISTS spectral_index_definitions (
    index_id            smallint PRIMARY KEY CHECK (index_id BETWEEN 1 AND 17),
    index_code          text NOT NULL UNIQUE,
    target_physics      text NOT NULL,
    formula_type        text NOT NULL CHECK (
        formula_type IN (
            'DEPTH_D',
            'EQUIV_WIDTH_W',
            'LINE_FLUX_DELTA_F',
            'BLUE_EXTRAP_RATIO',
            'NSDI',
            'COLOR_RATIO'
        )
    ),
    feature_channels    smallint[] NOT NULL DEFAULT '{}',
    blue_anchor_channel smallint REFERENCES spherex_channels (channel_id),
    red_anchor_channel  smallint REFERENCES spherex_channels (channel_id),
    band_a              smallint CHECK (band_a BETWEEN 1 AND 6),
    band_b              smallint CHECK (band_b BETWEEN 1 AND 6),
    discriminator_note  text NOT NULL
);

-- Per-exposure sector coordinates, NASA IRSA TAP p.poly footprints, FITS WCS, ZODI, and photometry.
CREATE TABLE IF NOT EXISTS nasa_sector_exposures (
    id                          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id                    bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    timeline_id                 bigint REFERENCES timelines (id) ON DELETE CASCADE,
    detector                    smallint NOT NULL CHECK (detector BETWEEN 1 AND 6),
    epoch_index                 smallint NOT NULL,
    uri                         text NOT NULL,
    release                     text NOT NULL,
    plane_id                    text,
    energy_bandpassname         text NOT NULL,
    nasa_poly_icrs              text,
    energy_bounds_lower_m       double precision,
    energy_bounds_upper_m       double precision,
    time_exposure_s             double precision,
    mjd_start                   double precision NOT NULL,
    mjd_end                     double precision NOT NULL,
    mid_mjd                     double precision NOT NULL,
    cutout_center_ra            double precision NOT NULL,
    cutout_center_dec           double precision NOT NULL,
    cutout_size_deg             double precision NOT NULL,
    cutout_corners_icrs         jsonb,
    wcs_header_json             jsonb,
    target_pix_x                double precision,
    target_pix_y                double precision,
    wavelength_um               double precision,
    bandwidth_um                double precision,
    channel_id                  smallint REFERENCES spherex_channels (channel_id),
    zodi_median_mjy_sr          double precision,
    target_flux_mjy_sr          double precision,
    target_variance_mjy_sr2     double precision,
    aperture_flux_ujy           double precision,
    aperture_sigma_stat_ujy     double precision,
    aperture_sigma_reported_ujy double precision,
    flags_bitmask_center        bigint,
    science_bad_fraction        double precision,
    clean_pixel_fraction        double precision,
    cutout_url                  text,
    sha256_hex                  text,
    local_cache_path            text,
    gcs_uri                     text,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patch_id, detector, uri)
);

CREATE INDEX IF NOT EXISTS idx_nasa_sector_exposures_patch_det
    ON nasa_sector_exposures (patch_id, detector, mjd_start);

-- Any OVERFLOW/SUR_ERROR pixel in the 5x5 photometry box at the object's propagated position.
ALTER TABLE nasa_sector_exposures
    ADD COLUMN IF NOT EXISTS saturated_near_target boolean;

CREATE INDEX IF NOT EXISTS idx_nasa_sector_exposures_channel
    ON nasa_sector_exposures (patch_id, channel_id);

-- General SHA-256 keyed cache for external NASA IRSA TAP / Gaia DR3 / CatWISE2020 queries.
CREATE TABLE IF NOT EXISTS api_query_cache (
    cache_key       text PRIMARY KEY,
    provider        text NOT NULL,
    query_text      text,
    request_params  jsonb NOT NULL DEFAULT '{}'::jsonb,
    response_json   jsonb NOT NULL,
    row_count       integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz
);

CREATE INDEX IF NOT EXISTS idx_api_query_cache_provider
    ON api_query_cache (provider, expires_at);

-- Inventory of artifacts mirrored to Google Cloud Storage (FITS cutouts, NPZ cubes, PNG renders).
CREATE TABLE IF NOT EXISTS gcs_media_assets (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_kind      text NOT NULL CHECK (
        asset_kind IN ('fits_cutout', 'npz_cube', 'png_render', 'spectrum_json', 'model_artifact')
    ),
    patch_id        bigint REFERENCES patches (id) ON DELETE CASCADE,
    timeline_id     bigint REFERENCES timelines (id) ON DELETE CASCADE,
    exposure_uri    text,
    bucket          text NOT NULL,
    object_name     text NOT NULL,
    gcs_uri         text NOT NULL UNIQUE,
    local_path      text,
    sha256_hex      text,
    crc32c          text,
    byte_size       bigint,
    content_type    text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gcs_media_assets_patch
    ON gcs_media_assets (patch_id, asset_kind);

-- Consolidated 102-channel spectra per patch (epoch_index = -1 means all_epochs aggregate).
-- Enforces Golden Rule #1: BLANKCH channels 51 and 52 remain NULL and invalid (never zero-imputed).
CREATE TABLE IF NOT EXISTS patch_spectra (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id             bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    epoch_index          smallint NOT NULL DEFAULT -1,
    spectrum_scope       text NOT NULL CHECK (spectrum_scope IN ('all_epochs', 'single_epoch')),
    wavelengths_um       double precision[] NOT NULL,
    flux_mjy             double precision[] NOT NULL,
    variance_mjy2        double precision[] NOT NULL,
    sigma_reported_mjy   double precision[] NOT NULL,
    valid_mask           boolean[] NOT NULL,
    channel_hit_counts   integer[] NOT NULL,
    band_coadd_flux_mjy  jsonb NOT NULL DEFAULT '{}'::jsonb,
    valid_channel_count  smallint NOT NULL,
    blankch_51_is_null   boolean NOT NULL DEFAULT TRUE CHECK (blankch_51_is_null),
    blankch_52_is_null   boolean NOT NULL DEFAULT TRUE CHECK (blankch_52_is_null),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patch_id, epoch_index),
    CHECK (array_length(wavelengths_um, 1) = 102),
    CHECK (array_length(flux_mjy, 1) = 102),
    CHECK (array_length(variance_mjy2, 1) = 102),
    CHECK (array_length(sigma_reported_mjy, 1) = 102),
    CHECK (array_length(valid_mask, 1) = 102),
    CHECK (array_length(channel_hit_counts, 1) = 102),
    CHECK (flux_mjy[51] IS NULL AND flux_mjy[52] IS NULL),
    CHECK (NOT valid_mask[51] AND NOT valid_mask[52])
);

-- Precomputed 17 diagnostic spectral indices with analytical uncertainties & 3-sigma flag.
CREATE TABLE IF NOT EXISTS patch_spectral_indices (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    spectrum_id       bigint NOT NULL REFERENCES patch_spectra (id) ON DELETE CASCADE,
    patch_id          bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    index_code        text NOT NULL REFERENCES spectral_index_definitions (index_code),
    value             double precision,
    uncertainty       double precision,
    snr               double precision,
    is_significant_3s boolean NOT NULL DEFAULT FALSE,
    is_valid          boolean NOT NULL DEFAULT FALSE,
    details_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
    computed_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (spectrum_id, index_code)
);

-- Model 1: Spatio-temporal event & artifact classifier + TreeSHAP attribution cache.
CREATE TABLE IF NOT EXISTS ml_model1_attributions (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id          bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    epoch_index       smallint NOT NULL DEFAULT -1,
    feature_vector    jsonb NOT NULL,
    predicted_class   text NOT NULL CHECK (
        predicted_class IN ('MOVING_OBJECT', 'VARIABLE_STAR_OR_TRANSIENT', 'AIRGLOW_OR_ZODI_STRIPE',
                            'INSTRUMENTAL_ARTIFACT', 'EXTENDED_EMISSION')
    ),
    temperature_t     double precision NOT NULL DEFAULT 1.0,
    probabilities     jsonb NOT NULL,
    treeshap_values   jsonb NOT NULL,
    citizen_level1    jsonb NOT NULL,
    researcher_level2 jsonb NOT NULL,
    model_version     text NOT NULL DEFAULT 'v1',
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patch_id, epoch_index, model_version)
);

-- Model 2: Spectral template chi2 + Bayesian fusion classifier cache.
CREATE TABLE IF NOT EXISTS ml_model2_classifications (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id            bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    spectrum_id         bigint REFERENCES patch_spectra (id) ON DELETE SET NULL,
    predicted_class     text NOT NULL CHECK (
        predicted_class IN ('ULTRACOLD_Y_DWARF', 'COLD_BROWN_DWARF_T', 'HIGH_PROPER_MOTION_M_DWARF',
                            'YOUNG_STELLAR_OBJECT_ACCRETION', 'PULSATING_MIRA_VARIABLE',
                            'SOLAR_SYSTEM_COMET')
    ),
    best_template_name  text,
    template_teff_k     double precision,
    template_log_g      double precision,
    scale_factor_c      double precision,
    scale_sigma_c       double precision,
    chi2_reduced        double precision,
    dof                 integer,
    valid_channels_used integer,
    ml_logits           jsonb NOT NULL DEFAULT '{}'::jsonb,
    bayesian_posteriors jsonb NOT NULL,
    citizen_level1      jsonb NOT NULL,
    researcher_level2   jsonb NOT NULL,
    model_version       text NOT NULL DEFAULT 'v1',
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patch_id, model_version)
);

-- Model 3: Temporal GP Celerite + astrometric cone forecaster & Model 1 alert handshake.
CREATE TABLE IF NOT EXISTS ml_model3_forecasts (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id              bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    model1_attribution_id bigint REFERENCES ml_model1_attributions (id) ON DELETE SET NULL,
    gp_hyperparams        jsonb NOT NULL,
    forecast_series       jsonb NOT NULL,
    predicted_cone        jsonb NOT NULL,
    z_alert               double precision,
    mahalanobis_d2        double precision,
    delta_log_likelihood  double precision,
    alert_triggered       boolean NOT NULL DEFAULT FALSE,
    citizen_level1        jsonb NOT NULL,
    researcher_level2     jsonb NOT NULL,
    model_version         text NOT NULL DEFAULT 'v1',
    created_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patch_id, model_version)
);

-- Citizen science 1-click consensus votes per patch and epoch.
CREATE TABLE IF NOT EXISTS citizen_votes (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patch_id    bigint NOT NULL REFERENCES patches (id) ON DELETE CASCADE,
    epoch_index smallint NOT NULL DEFAULT 0,
    vote        text NOT NULL CHECK (vote IN ('REAL_CHANGE', 'ARTIFACT', 'MOVER', 'UNSURE')),
    voter_token text,
    comment     text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_citizen_votes_patch
    ON citizen_votes (patch_id, epoch_index);

-- Migration: databases created before Nov 2026 have the first draft of these value lists, which
-- no longer match app/models.py (MODEL1_CLASSES, the Model 2 templates) and the vote values of
-- app/main.py, so every insert failed with a CheckViolation. CREATE TABLE IF NOT EXISTS does not
-- touch existing tables, so the checks are replaced here. Idempotent; NOT VALID keeps any older
-- rows instead of failing on them, and every new row is still checked.
ALTER TABLE ml_model1_attributions
    DROP CONSTRAINT IF EXISTS ml_model1_attributions_predicted_class_check;
ALTER TABLE ml_model1_attributions
    ADD CONSTRAINT ml_model1_attributions_predicted_class_check CHECK (
        predicted_class IN ('MOVING_OBJECT', 'VARIABLE_STAR_OR_TRANSIENT', 'AIRGLOW_OR_ZODI_STRIPE',
                            'INSTRUMENTAL_ARTIFACT', 'EXTENDED_EMISSION')
    ) NOT VALID;
ALTER TABLE ml_model2_classifications
    DROP CONSTRAINT IF EXISTS ml_model2_classifications_predicted_class_check;
ALTER TABLE ml_model2_classifications
    ADD CONSTRAINT ml_model2_classifications_predicted_class_check CHECK (
        predicted_class IN ('ULTRACOLD_Y_DWARF', 'COLD_BROWN_DWARF_T', 'HIGH_PROPER_MOTION_M_DWARF',
                            'YOUNG_STELLAR_OBJECT_ACCRETION', 'PULSATING_MIRA_VARIABLE',
                            'SOLAR_SYSTEM_COMET')
    ) NOT VALID;
-- Public chat (app/chat.py): one room per catalogue object plus 'general'. Anonymous: the
-- nickname is generated in the browser and nothing identifies the sender. Rows older than 24 h
-- are deleted by the API, so the table only ever holds one day of messages.
CREATE TABLE IF NOT EXISTS chat_messages (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room        text NOT NULL CHECK (room ~ '^[a-z0-9-]{1,64}$'),
    nickname    text NOT NULL CHECK (char_length(nickname) <= 32),
    body        text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 280),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_room ON chat_messages (room, id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages (created_at);

ALTER TABLE citizen_votes DROP CONSTRAINT IF EXISTS citizen_votes_vote_check;
ALTER TABLE citizen_votes
    ADD CONSTRAINT citizen_votes_vote_check CHECK (
        vote IN ('REAL_CHANGE', 'ARTIFACT', 'MOVER', 'UNSURE')
    ) NOT VALID;
