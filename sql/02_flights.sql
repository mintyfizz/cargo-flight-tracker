-- Step 2: cargo flights and hub activity
-- Input:  stg_states, reference/cargo_operators.csv, reference/hubs.csv
-- Output: cargo_states  one row per cargo aircraft per snapshot
--         cargo_flights one row per flight (consecutive airborne snapshots of one aircraft)
--         hub_visits    one row per cargo aircraft seen at a hub, per snapshot

CREATE OR REPLACE MACRO distance_km(lat1, lon1, lat2, lon2) AS
    2 * 6371 * asin(sqrt(
        pow(sin(radians(lat2 - lat1) / 2), 2)
        + cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lon2 - lon1) / 2), 2)
    ));

-- A flight is cargo when the first three letters of its callsign are a cargo airline code
CREATE OR REPLACE TABLE cargo_states AS
SELECT s.*, o.operator, o."group" AS operator_group
FROM stg_states s
JOIN read_csv('reference/cargo_operators.csv') o
  ON left(s.callsign, 3) = o.icao_prefix;

-- Group the airborne snapshots of each aircraft into flights. A new flight starts when the
-- callsign changes, or when the aircraft was not seen in the air for more than 45 minutes.
CREATE OR REPLACE TABLE cargo_flights AS
WITH airborne AS (
    SELECT *,
        lag(snapshot_at) OVER w AS previous_at,
        lag(callsign)    OVER w AS previous_callsign
    FROM cargo_states
    WHERE NOT on_ground
    WINDOW w AS (PARTITION BY icao24 ORDER BY snapshot_at)
),
numbered AS (
    SELECT *,
        sum(CASE
                WHEN previous_at IS NULL
                  OR callsign <> previous_callsign
                  OR snapshot_at - previous_at > INTERVAL 45 MINUTE
                THEN 1 ELSE 0
            END) OVER (PARTITION BY icao24 ORDER BY snapshot_at) AS flight_number
    FROM airborne
)
SELECT
    icao24,
    callsign,
    any_value(operator)                     AS operator,
    any_value(operator_group)               AS operator_group,
    min(snapshot_at)                        AS first_seen_at,
    max(snapshot_at)                        AS last_seen_at,
    count(*)                                AS snapshots,
    arg_min(lat, snapshot_at)               AS first_lat,
    arg_min(lon, snapshot_at)               AS first_lon,
    arg_max(lat, snapshot_at)               AS last_lat,
    arg_max(lon, snapshot_at)               AS last_lon,
    round(max(altitude_m))                  AS max_altitude_m,
    round(distance_km(arg_min(lat, snapshot_at), arg_min(lon, snapshot_at),
                      arg_max(lat, snapshot_at), arg_max(lon, snapshot_at))) AS distance_seen_km
FROM numbered
GROUP BY icao24, callsign, flight_number;

-- Cargo aircraft at a hub: on the ground, or below 1,500 m, within 10 km of the airport
CREATE OR REPLACE TABLE hub_visits AS
SELECT c.snapshot_at, h.iata AS hub, h.name AS hub_name, c.icao24, c.callsign, c.operator, c.operator_group, c.on_ground
FROM cargo_states c
JOIN read_csv('reference/hubs.csv') h
  ON c.lat BETWEEN h.lat - 0.2 AND h.lat + 0.2
 AND c.lon BETWEEN h.lon - 0.3 AND h.lon + 0.3
WHERE distance_km(c.lat, c.lon, h.lat, h.lon) <= 10
  AND (c.on_ground OR c.altitude_m < 1500);
