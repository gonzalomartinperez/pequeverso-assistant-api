-- Revision1.1: persist analytics classification; old fixture facts remain synthetic/unknown.
-- Append-only successor: migration005 and its historical tables are never rewritten.
CREATE TABLE IF NOT EXISTS assistant_private.analytics_schema_v2 (
    version integer PRIMARY KEY CHECK(version = 2),
    checksum text NOT NULL CHECK(checksum ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS assistant_private.analytics_daily_v2 (
    synthetic boolean NOT NULL,
    day timestamptz NOT NULL,
    route text NOT NULL CHECK(route IN ('/','/grafismo-fonetico/')),
    section_id text NOT NULL,
    viewport_bucket text NOT NULL CHECK(viewport_bucket IN ('mobile','tablet','desktop')),
    event_name text NOT NULL CHECK(event_name IN ('page_view','section_view','public_click')),
    country text NOT NULL CHECK(country IN ('AD','AE','AF','AG','AI','AL','AM','AO','AQ','AR','AS','AT','AU','AW','AX','AZ','BA','BB','BD','BE','BF','BG','BH','BI','BJ','BL','BM','BN','BO','BQ','BR','BS','BT','BV','BW','BY','BZ','CA','CC','CD','CF','CG','CH','CI','CK','CL','CM','CN','CO','CR','CU','CV','CW','CX','CY','CZ','DE','DJ','DK','DM','DO','DZ','EC','EE','EG','EH','ER','ES','ET','FI','FJ','FK','FM','FO','FR','GA','GB','GD','GE','GF','GG','GH','GI','GL','GM','GN','GP','GQ','GR','GS','GT','GU','GW','GY','HK','HM','HN','HR','HT','HU','ID','IE','IL','IM','IN','IO','IQ','IR','IS','IT','JE','JM','JO','JP','KE','KG','KH','KI','KM','KN','KP','KR','KW','KY','KZ','LA','LB','LC','LI','LK','LR','LS','LT','LU','LV','LY','MA','MC','MD','ME','MF','MG','MH','MK','ML','MM','MN','MO','MP','MQ','MR','MS','MT','MU','MV','MW','MX','MY','MZ','NA','NC','NE','NF','NG','NI','NL','NO','NP','NR','NU','NZ','OM','PA','PE','PF','PG','PH','PK','PL','PM','PN','PR','PS','PT','PW','PY','QA','RE','RO','RS','RU','RW','SA','SB','SC','SD','SE','SG','SH','SI','SJ','SK','SL','SM','SN','SO','SR','SS','ST','SV','SX','SY','SZ','TC','TD','TF','TG','TH','TJ','TK','TL','TM','TN','TO','TR','TT','TV','TW','TZ','UA','UG','UM','US','UY','UZ','VA','VC','VE','VG','VI','VN','VU','WF','WS','YE','YT','ZA','ZM','ZW','unknown')),
    cell_x integer NOT NULL,
    cell_y integer NOT NULL,
    count integer NOT NULL CHECK(count BETWEEN 1 AND 10000),
    first_received timestamptz NOT NULL,
    last_received timestamptz NOT NULL CHECK(last_received >= first_received),
    CHECK((route='/' AND section_id IN ('hero','leer','bebe','preguntas')) OR
          (route='/grafismo-fonetico/' AND section_id IN ('hero','incluye','metodo','preguntas'))),
    CHECK((event_name='public_click' AND cell_x BETWEEN 0 AND 7 AND cell_y BETWEEN 0 AND 7) OR
          (event_name<>'public_click' AND cell_x=-1 AND cell_y=-1)),
    PRIMARY KEY(synthetic,day,route,section_id,viewport_bucket,event_name,country,cell_x,cell_y)
);
CREATE INDEX IF NOT EXISTS analytics_daily_v2_expiry ON assistant_private.analytics_daily_v2(day);
INSERT INTO assistant_private.analytics_daily_v2
    (synthetic,day,route,section_id,viewport_bucket,event_name,country,cell_x,cell_y,count,first_received,last_received)
SELECT true,day,route,section_id,viewport_bucket,event_name,'unknown',cell_x,cell_y,count,first_received,last_received
FROM assistant_private.analytics_daily
ON CONFLICT(synthetic,day,route,section_id,viewport_bucket,event_name,country,cell_x,cell_y) DO NOTHING;
REVOKE ALL ON assistant_private.analytics_schema_v2,assistant_private.analytics_daily_v2 FROM PUBLIC;
GRANT SELECT ON assistant_private.analytics_schema_v2 TO pequeverso_private_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON assistant_private.analytics_daily_v2 TO pequeverso_private_runtime;
