-- Step 3: KPI tables (kpi_*), exported as JSON by run_pipeline.py
-- Input:  stg_states, cargo_states, cargo_flights, hub_visits, and the route coverage log

-- How much of the air traffic is cargo, hour by hour (UTC)
CREATE OR REPLACE TABLE kpi_cargo_share_by_hour AS
WITH per_snapshot AS (
    SELECT s.snapshot_at,
        count(*) FILTER (WHERE NOT s.on_ground)                                AS aircraft_airborne,
        count(*) FILTER (WHERE NOT s.on_ground AND c.icao24 IS NOT NULL)       AS cargo_airborne
    FROM stg_states s
    LEFT JOIN cargo_states c USING (snapshot_at, icao24)
    GROUP BY s.snapshot_at
)
SELECT
    date_trunc('hour', snapshot_at)                              AS hour_utc,
    count(*)                                                     AS snapshots,
    round(avg(aircraft_airborne))                                AS avg_aircraft_airborne,
    round(avg(cargo_airborne))                                   AS avg_cargo_airborne,
    round(100.0 * sum(cargo_airborne) / sum(aircraft_airborne), 1) AS cargo_share_pct
FROM per_snapshot
GROUP BY ALL
ORDER BY hour_utc;

-- Flights and aircraft per airline
CREATE OR REPLACE TABLE kpi_flights_per_operator AS
SELECT
    operator_group,
    operator,
    count(*)                        AS flights,
    count(DISTINCT icao24)          AS aircraft,
    round(avg(max_altitude_m))      AS avg_max_altitude_m
FROM cargo_flights
GROUP BY ALL
ORDER BY flights DESC;

-- Busiest hubs: different cargo aircraft seen at each hub, per hour (UTC)
CREATE OR REPLACE TABLE kpi_busiest_hubs_by_hour AS
SELECT
    hub,
    hub_name,
    date_trunc('hour', snapshot_at)                 AS hour_utc,
    count(DISTINCT icao24)                          AS cargo_aircraft,
    count(DISTINCT icao24) FILTER (WHERE on_ground) AS on_the_ground
FROM hub_visits
GROUP BY ALL
ORDER BY hour_utc, cargo_aircraft DESC;

-- How often the route step finds a departure and a destination (one log line per pipeline run)
CREATE OR REPLACE TABLE kpi_route_coverage AS
SELECT
    count(*)                                                            AS runs,
    min(fetched_at)                                                     AS first_run_at,
    max(fetched_at)                                                     AS last_run_at,
    sum(airborne)                                                       AS flights_checked,
    round(100.0 * sum(departure_measured) / nullif(sum(airborne), 0), 1)    AS departure_measured_pct,
    round(100.0 * sum(destination_confirmed) / nullif(sum(airborne), 0), 1) AS destination_confirmed_pct
FROM read_csv(
    getvariable('coverage_csv'),
    columns = {'fetched_at': 'TIMESTAMPTZ', 'airborne': 'INTEGER', 'departure_measured': 'INTEGER', 'destination_confirmed': 'INTEGER'},
    header = true
);
