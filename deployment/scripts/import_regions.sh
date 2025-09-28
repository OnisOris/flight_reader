#!/usr/bin/env bash
set -euo pipefail

# Configuration
PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDB="${POSTGRES_DB:-flight_reader}"
PGUSER="${POSTGRES_USER:-flight_reader}"
PGPASSWORD="${POSTGRES_PASSWORD:-flight_reader_password}"
export PGPASSWORD

SRC_DIR="/data"
SRC_FILE="${SRC_FILE:-}"  # allow override
SRC_URL="${REGIONS_SOURCE_URL:-}"
OSMB_API_KEY="${OSMB_API_KEY:-}"

log() { printf '[regions-import] %s\n' "$*" >&2; }

wait_for_db() {
  log "Waiting for Postgres at ${PGHOST}:${PGPORT} ..."
  for i in {1..60}; do
    if psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDB" -tAc 'SELECT 1' >/dev/null 2>&1; then
      log "Postgres is ready"
      return 0
    fi
    sleep 1
  done
  log "Postgres is not reachable" >&2
  return 1
}

pick_source() {
  if [[ -n "$SRC_FILE" && -f "$SRC_FILE" ]]; then
    echo "$SRC_FILE"; return 0
  fi
  for name in regions.geojson regions.json regions.shp regions.gpkg; do
    if [[ -f "${SRC_DIR}/${name}" ]]; then
      echo "${SRC_DIR}/${name}"; return 0
    fi
  done
  if [[ -n "$SRC_URL" ]]; then
    TMP="/tmp/regions.geojson"
    log "Downloading regions from ${SRC_URL} ..."
    if [[ -n "$OSMB_API_KEY" ]]; then
      curl -fsSL -H "X-OSMB-Api-Key: ${OSMB_API_KEY}" "$SRC_URL" -o "$TMP" || return 1
    else
      curl -fsSL "$SRC_URL" -o "$TMP" || return 1
    fi
    if head -c 2 "$TMP" 2>/dev/null | od -An -tx1 2>/dev/null | grep -q "1f 8b"; then
      log "Detected gzip-encoded dataset, decompressing ..."
      gunzip -c "$TMP" > "${TMP}.unzipped" && mv "${TMP}.unzipped" "$TMP"
    fi
    echo "$TMP"; return 0
  fi
  return 1
}

wait_for_db

if ! SRC_PATH=$(pick_source); then
  log "No source dataset provided or download failed. Place a file into deployment/data (regions.geojson/shp/gpkg) or set REGIONS_SOURCE_URL/OSMB_API_KEY."
  exit 1
fi

log "Using source: ${SRC_PATH}"

# Import raw layer into staging table regions_tmp (overwrite)
log "Importing into staging table regions_tmp via ogr2ogr ..."
ogr2ogr -skipfailures \
  -f PostgreSQL \
  PG:"host=${PGHOST} port=${PGPORT} dbname=${PGDB} user=${PGUSER} password=${PGPASSWORD}" \
  "${SRC_PATH}" \
  -nln regions_tmp \
  -lco GEOMETRY_NAME=geom \
  -nlt MULTIPOLYGON \
  -overwrite \
  >/dev/null

log "Staging import complete, normalizing into regions ..."

psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDB" -v ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='regions_tmp' AND column_name ILIKE 'ISO3166-2') THEN
    RAISE NOTICE 'Column ISO3166-2 not found — codes will be generated from names';
  END IF;
END $$;

-- Create helper function to generate code from name when missing
CREATE OR REPLACE FUNCTION _gen_region_code(in_name text) RETURNS text AS $$
DECLARE base text;
BEGIN
  IF in_name IS NULL OR length(trim(in_name)) = 0 THEN
    RETURN NULL;
  END IF;
  base := upper(in_name);
  RETURN 'RU-' || substring(md5(base) for 8);
END; $$ LANGUAGE plpgsql;

-- Upsert into regions from staging, preferring ISO code, then name-based synthetic code
WITH normalized AS (
  SELECT
    (SELECT value FROM jsonb_each_text(to_jsonb(rt)) WHERE key IN ('ISO3166-2', 'iso3166_2', 'ISO31662') LIMIT 1) AS iso_code,
    (SELECT value FROM jsonb_each_text(to_jsonb(rt)) WHERE key IN ('name:ru', 'name_ru', 'NAME_RU', 'name', 'NAME') LIMIT 1) AS region_name,
    (SELECT value FROM jsonb_each_text(to_jsonb(rt)) WHERE key IN ('admin_level','ADMIN_LEVEL') LIMIT 1) AS admin_level,
    ST_Multi(ST_CollectionExtract(ST_MakeValid(rt.geom), 3)) AS geom
  FROM regions_tmp rt
), prepared AS (
  SELECT
    CASE
      WHEN iso_code IS NOT NULL THEN iso_code
      ELSE _gen_region_code(region_name)
    END AS final_code,
    COALESCE(region_name, iso_code) AS display_name,
    admin_level,
    geom
  FROM normalized
  WHERE (region_name IS NOT NULL OR iso_code IS NOT NULL)
), aggregated AS (
  SELECT
    final_code,
    MAX(display_name) FILTER (WHERE display_name IS NOT NULL) AS region_name,
    ST_Multi(ST_CollectionExtract(ST_UnaryUnion(ST_Collect(geom)), 3)) AS geom
  FROM prepared
  WHERE admin_level = '4'
  GROUP BY final_code
)
INSERT INTO regions (code, name, geom)
SELECT
  final_code AS code,
  region_name AS name,
  geom
FROM aggregated
ON CONFLICT (code) DO UPDATE
  SET name = EXCLUDED.name,
      geom = EXCLUDED.geom;

CREATE INDEX IF NOT EXISTS idx_regions_geom ON regions USING GIST (geom);
ANALYZE regions;

DROP TABLE IF EXISTS regions_tmp;
SQL

log "Regions import finished."
