-- Local, OFF-by-default received-event aggregates. No visitor/session/conversation joins.
CREATE TABLE IF NOT EXISTS assistant_private.analytics_schema (
    version integer PRIMARY KEY CHECK(version = 1),
    checksum text NOT NULL CHECK(checksum ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS assistant_private.analytics_dedupe (
    digest text PRIMARY KEY CHECK(digest ~ '^[0-9a-f]{64}$'),
    received_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS analytics_dedupe_expiry ON assistant_private.analytics_dedupe(received_at);
CREATE TABLE IF NOT EXISTS assistant_private.analytics_quotas (
    period text NOT NULL CHECK(period IN ('minute','day')),
    bucket timestamptz NOT NULL,
    accepted integer NOT NULL CHECK(accepted BETWEEN 1 AND 10000),
    PRIMARY KEY(period,bucket)
);
CREATE TABLE IF NOT EXISTS assistant_private.analytics_daily (
    day timestamptz NOT NULL,
    route text NOT NULL CHECK(route IN ('/','/grafismo-fonetico/')),
    section_id text NOT NULL,
    viewport_bucket text NOT NULL CHECK(viewport_bucket IN ('mobile','tablet','desktop')),
    event_name text NOT NULL CHECK(event_name IN ('page_view','section_view','public_click')),
    cell_x integer NOT NULL,
    cell_y integer NOT NULL,
    count integer NOT NULL CHECK(count BETWEEN 1 AND 10000),
    first_received timestamptz NOT NULL,
    last_received timestamptz NOT NULL CHECK(last_received >= first_received),
    CHECK((route='/' AND section_id IN ('hero','leer','bebe','preguntas')) OR
          (route='/grafismo-fonetico/' AND section_id IN ('hero','incluye','metodo','preguntas'))),
    CHECK((event_name='public_click' AND cell_x BETWEEN 0 AND 7 AND cell_y BETWEEN 0 AND 7) OR
          (event_name<>'public_click' AND cell_x=-1 AND cell_y=-1)),
    PRIMARY KEY(day,route,section_id,viewport_bucket,event_name,cell_x,cell_y)
);
REVOKE ALL ON assistant_private.analytics_schema,assistant_private.analytics_dedupe,
    assistant_private.analytics_quotas,assistant_private.analytics_daily FROM PUBLIC;
GRANT SELECT ON assistant_private.analytics_schema TO pequeverso_private_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON assistant_private.analytics_dedupe,
    assistant_private.analytics_quotas,assistant_private.analytics_daily TO pequeverso_private_runtime;
