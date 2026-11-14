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
    UNIQUE (timeline_id, epoch_index, size)
);
