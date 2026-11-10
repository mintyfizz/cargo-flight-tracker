"""Turn the latest raw snapshot into the small live file the map reads.

Input:  the newest data/raw/states/date=*/HHMMSS.json.gz (or RAW_DIR)
Output: dashboard/data/live.json, cargo flights only, with readable field names,
        plus each flight's departure and destination airport (see routes.py)
"""

import csv
import gzip
import json
import os
from pathlib import Path

from routes import add_routes

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(os.getenv("RAW_DIR", ROOT / "data" / "raw" / "states"))
OUT_FILE = ROOT / "dashboard" / "data" / "live.json"
ROUTE_CACHE = RAW_DIR.parent / "routes" / "cache.json"

# Position of each field in an OpenSky state vector (see the API docs)
ICAO24, CALLSIGN, COUNTRY, TIME_POS, LAST_CONTACT, LON, LAT, BARO_ALT, ON_GROUND, VELOCITY, TRACK = range(11)


def load_operators() -> dict[str, dict]:
    with open(ROOT / "reference" / "cargo_operators.csv") as f:
        return {row["icao_prefix"]: row for row in csv.DictReader(f)}


def main() -> None:
    latest = max(RAW_DIR.glob("date=*/*.json.gz"))
    with gzip.open(latest, "rt") as f:
        snapshot = json.load(f)

    operators = load_operators()
    flights = []
    for s in snapshot.get("states") or []:
        callsign = (s[CALLSIGN] or "").strip()
        op = operators.get(callsign[:3])
        if not op or s[LAT] is None or s[LON] is None:
            continue
        flights.append(
            {
                "callsign": callsign,
                "icao24": s[ICAO24],
                "operator": op["operator"],
                "group": op["group"],
                "lat": round(s[LAT], 4),
                "lon": round(s[LON], 4),
                "altitude_m": round(s[BARO_ALT]) if s[BARO_ALT] is not None else None,
                "speed_kmh": round(s[VELOCITY] * 3.6) if s[VELOCITY] is not None else None,
                "heading": round(s[TRACK]) if s[TRACK] is not None else None,
                "on_ground": s[ON_GROUND],
                "last_contact": s[LAST_CONTACT],
            }
        )

    add_routes(flights, ROUTE_CACHE, snapshot["fetched_at"])

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(
            {
                "fetched_at": snapshot["fetched_at"],
                "api_time": snapshot.get("time"),
                "aircraft_worldwide": len(snapshot.get("states") or []),
                "flights": flights,
            }
        )
    )
    print(f"{len(flights)} cargo flights written to {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
