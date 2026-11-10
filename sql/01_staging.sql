-- Step 1: flatten the raw API snapshots
-- Input:  one gzipped JSON file per snapshot (raw_glob), where "states" is a list of arrays,
--         one array per aircraft (field order: see the OpenSky API docs)
-- Output: stg_states, one row per aircraft per snapshot

CREATE OR REPLACE TABLE stg_states AS
WITH snapshots AS (
    SELECT "time" AS api_time, unnest(states) AS s
    FROM read_json(
        getvariable('raw_glob'),
        columns = {'time': 'BIGINT', 'states': 'JSON[]'},
        maximum_object_size = 200000000
    )
)
SELECT
    to_timestamp(api_time)                          AS snapshot_at,
    s ->> '$[0]'                                    AS icao24,
    nullif(trim(s ->> '$[1]'), '')                  AS callsign,
    s ->> '$[2]'                                    AS origin_country,
    to_timestamp((s ->> '$[4]')::BIGINT)            AS last_contact_at,
    (s ->> '$[5]')::DOUBLE                          AS lon,
    (s ->> '$[6]')::DOUBLE                          AS lat,
    (s ->> '$[7]')::DOUBLE                          AS altitude_m,
    (s ->> '$[8]')::BOOLEAN                         AS on_ground,
    (s ->> '$[9]')::DOUBLE * 3.6                    AS speed_kmh,
    (s ->> '$[10]')::DOUBLE                         AS heading
FROM snapshots
WHERE (s ->> '$[5]') IS NOT NULL
  AND (s ->> '$[6]') IS NOT NULL;
