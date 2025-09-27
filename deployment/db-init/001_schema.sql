CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS operators (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    extra JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS uav_types (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS regions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(16) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    geom geometry(MULTIPOLYGON, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_messages (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sender VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS flights (
    id SERIAL PRIMARY KEY,
    flight_id VARCHAR(64) NOT NULL,
    operator_id INTEGER NOT NULL REFERENCES operators(id),
    uav_type_id INTEGER NOT NULL REFERENCES uav_types(id),
    takeoff_time TIMESTAMPTZ,
    landing_time TIMESTAMPTZ,
    duration INTERVAL,
    geom_takeoff geometry(POINT, 4326),
    geom_landing geometry(POINT, 4326),
    region_from_id INTEGER REFERENCES regions(id),
    region_to_id INTEGER REFERENCES regions(id),
    raw_msg_id INTEGER REFERENCES raw_messages(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_flights_flight_time UNIQUE (flight_id, takeoff_time, landing_time)
);

CREATE TABLE IF NOT EXISTS flights_history (
    id SERIAL PRIMARY KEY,
    flight_id INTEGER NOT NULL REFERENCES flights(id),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    snapshot JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    auth_id VARCHAR(128) UNIQUE NOT NULL,
    role VARCHAR(32) NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS upload_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_file VARCHAR(255),
    flight_count INTEGER DEFAULT 0,
    status VARCHAR(32) NOT NULL,
    details TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS calculations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    parameters JSONB NOT NULL DEFAULT '{}',
    result_summary JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    report_type VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    parameters JSONB NOT NULL DEFAULT '{}',
    content JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_flights_takeoff ON flights (takeoff_time);
CREATE INDEX IF NOT EXISTS ix_flights_landing ON flights (landing_time);
CREATE INDEX IF NOT EXISTS ix_flights_operator ON flights (operator_id);
CREATE INDEX IF NOT EXISTS ix_flights_uav_type ON flights (uav_type_id);
CREATE INDEX IF NOT EXISTS ix_flights_region_from ON flights (region_from_id);
CREATE INDEX IF NOT EXISTS ix_flights_region_to ON flights (region_to_id);
CREATE INDEX IF NOT EXISTS ix_flights_geom_takeoff ON flights USING GIST (geom_takeoff);
CREATE INDEX IF NOT EXISTS ix_flights_geom_landing ON flights USING GIST (geom_landing);
CREATE INDEX IF NOT EXISTS idx_regions_geom ON regions USING GIST (geom);

INSERT INTO regions (code, name, geom)
VALUES
    (
        'RU-MOW',
        'Москва',
        ST_GeomFromText('MULTIPOLYGON(((37.20 55.55, 37.90 55.55, 37.90 56.00, 37.20 56.00, 37.20 55.55)))', 4326)
    ),
    (
        'RU-SPE',
        'Санкт-Петербург',
        ST_GeomFromText('MULTIPOLYGON(((29.60 59.70, 30.60 59.70, 30.60 60.20, 29.60 60.20, 29.60 59.70)))', 4326)
    )
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO operators (code, name)
VALUES
    ('BWS', 'BWS GEPRC CINEBOT30'),
    ('MORF', 'MORF State Authority')
ON CONFLICT (code) DO NOTHING;

INSERT INTO uav_types (code, description)
VALUES
    ('BLA', 'Multirotor drone'),
    ('FIX', 'Fixed wing UAV')
ON CONFLICT (code) DO NOTHING;

INSERT INTO users (auth_id, role, name, email)
VALUES
    ('seed-admin', 'admin', 'Seed Admin', 'admin@example.com')
ON CONFLICT (auth_id) DO NOTHING;
