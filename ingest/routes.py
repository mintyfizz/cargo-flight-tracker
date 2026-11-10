"""Work out where each airborne cargo flight actually took off, and where it is going.

Departure (measured): the aircraft's own recorded track is followed back to the point
where it left the ground, and that point is matched to the nearest airport.
Track source: adsb.lol (open ADS-B data, https://adsb.lol).

Destination (cross-checked): aircraft do not broadcast a destination, so it comes from
the scheduled route for the callsign, looked up in two independent route databases
(https://www.adsbdb.com and https://hexdb.io). A scheduled leg is only accepted when it
starts at the airport the aircraft really took off from and the aircraft is on the way
to its end. If the two databases disagree, or nothing matches, the destination is left empty.

Results are cached per flight, so each flight costs one track download.
"""

import csv
import json
import math
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TRACE_URL = "https://adsb.lol/data/traces/{sub}/trace_full_{icao24}.json"
ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
ROUTE_URL_2 = "https://hexdb.io/api/v1/route/icao/{callsign}"
HEADERS = {"User-Agent": "cargo-flight-tracker (github.com/mintyfizz/cargo-flight-tracker)"}

MAX_TRACES_PER_RUN = 400        # be polite to adsb.lol: one request per new flight
MAX_ROUTE_LOOKUPS_PER_RUN = 400
PAUSE_S = 0.15
GROUND_MATCH_KM = 6             # take-off point must be this close to an airport
CLIMB_MATCH_KM = 10             # same, when the track only starts just after take-off
CLIMB_MAX_FT_ABOVE_AIRPORT = 3000
PATH_POINTS = 20                # flown track kept for drawing, thinned to this many points
ROUTE_TTL_S = 7 * 86400
UNKNOWN_ROUTE_TTL_S = 86400


def dist_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(min(1.0, math.sqrt(a)))


class Airports:
    def __init__(self) -> None:
        self.grid: dict[tuple[int, int], list[dict]] = {}
        self.by_icao: dict[str, dict] = {}
        with open(ROOT / "reference" / "airports.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                a = {"code": r["iata"] or r["icao"], "icao": r["icao"], "city": r["city"] or r["name"], "name": r["name"],
                     "lat": float(r["lat"]), "lon": float(r["lon"]), "elevation_ft": float(r["elevation_ft"] or 0)}
                self.grid.setdefault((math.floor(a["lat"]), math.floor(a["lon"])), []).append(a)
                self.by_icao[a["icao"]] = a

    def nearest(self, lat: float, lon: float, max_km: float) -> dict | None:
        best, best_d = None, max_km
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for a in self.grid.get((math.floor(lat) + dy, (math.floor(lon) + dx + 180) % 360 - 180), []):
                    d = dist_km(lat, lon, a["lat"], a["lon"])
                    if d <= best_d:
                        best, best_d = a, d
        return best


def public(airport: dict) -> dict:
    return {k: airport[k] for k in ("code", "icao", "city", "lat", "lon")}


def find_departure(trace: dict, airports: Airports) -> dict | None:
    """Follow the track back from its latest point to where this flight left the ground."""
    t0 = trace.get("timestamp", 0)
    # Leave out "stale" points (flag 1): they repeat an old position with a new time
    pts = [p for p in trace.get("trace") or [] if not p[6] & 1]
    if not pts or pts[-1][3] == "ground":
        return None

    start, method = None, None
    for j in range(len(pts) - 1, -1, -1):
        p = pts[j]
        alt = p[3]
        if alt == "ground":
            nxt = pts[j + 1]
            if nxt[0] - p[0] <= 900:                      # seen on the ground, airborne right after
                start, method = j, "ground"
            elif isinstance(nxt[3], (int, float)) and nxt[3] <= 6000:
                start, method = j + 1, "climb"            # ground signal lost, picked up again in the climb
            break
        gap_before = p[0] - pts[j - 1][0] if j > 0 else None
        if j == 0 or gap_before > 1200:
            if isinstance(alt, (int, float)) and alt <= 6000:
                start, method = j, "climb"                # track begins low: just after take-off
                break
            if j == 0:
                break                                     # track begins at altitude: departure not recorded
            # A gap at altitude is normally just missing coverage (e.g. over an ocean). But if the aircraft
            # covered too little distance for the time it was out of sight, it may have landed and taken
            # off again somewhere unseen, and then the real departure is unknown.
            q = pts[j - 1]
            cruise_kmh = (p[4] or 430) * 1.852
            if dist_km(q[1], q[2], p[1], p[2]) / (gap_before / 3600) < 0.75 * cruise_kmh:
                break
    if start is None:
        return None

    p = pts[start]
    if method == "ground":
        airport = airports.nearest(p[1], p[2], GROUND_MATCH_KM)
    else:
        airport = airports.nearest(p[1], p[2], CLIMB_MATCH_KM)
        if airport and p[3] - airport["elevation_ft"] > CLIMB_MAX_FT_ABOVE_AIRPORT:
            airport = None
    if not airport:
        return None

    leg = pts[start + 1:]
    step = max(1, math.ceil(len(leg) / PATH_POINTS))
    path = [[round(q[1], 2), round(q[2], 2)] for q in leg[::step]]
    last = pts[-1]
    return {"airport": public(airport), "time": int(t0 + pts[min(start + 1, len(pts) - 1)][0]), "path": path,
            "trace_end": {"t": t0 + last[0], "lat": last[1], "lon": last[2]}}


def fetch_trace(session: requests.Session, icao24: str) -> dict | None:
    try:
        r = session.get(TRACE_URL.format(sub=icao24[-2:], icao24=icao24), headers=HEADERS, timeout=30)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def fetch_scheduled(session: requests.Session, callsign: str, airports: Airports) -> list[dict] | None:
    """Scheduled legs for a callsign from both route databases. None = a lookup failed (try again later)."""
    legs: list[dict] = []
    try:
        r = session.get(ROUTE_URL.format(callsign=callsign), headers=HEADERS, timeout=20)
        r2 = session.get(ROUTE_URL_2.format(callsign=callsign), headers=HEADERS, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code not in (200, 404) or r2.status_code not in (200, 404):
        return None

    if r.status_code == 200:
        fr = (r.json().get("response") or {}).get("flightroute") or {}
        if fr.get("origin") and fr.get("destination"):
            def apt(a: dict) -> dict:
                return {"code": a.get("iata_code") or a.get("icao_code"), "icao": a.get("icao_code"),
                        "city": a.get("municipality") or a.get("name"), "lat": a["latitude"], "lon": a["longitude"]}
            legs.append({"origin": apt(fr["origin"]), "destination": apt(fr["destination"]), "source": "adsbdb"})

    if r2.status_code == 200:
        try:
            stops = [airports.by_icao.get(code) for code in (r2.json().get("route") or "").split("-")]
        except ValueError:
            stops = []
        for a, b in zip(stops, stops[1:]):                # a route can have several legs: A-B-C
            if a and b:
                legs.append({"origin": public(a), "destination": public(b), "source": "hexdb"})
    return legs


def confirmed_destination(legs: list[dict], departure: dict, lat: float, lon: float) -> dict | None:
    """The destination of the scheduled leg(s) that start where the aircraft really took off."""
    found = [leg["destination"] for leg in legs
             if same_airport(departure, leg["origin"]) and on_the_way(leg["origin"], leg["destination"], lat, lon)]
    if found and all(same_airport(found[0], d) for d in found[1:]):
        return found[0]
    return None                                           # nothing matches, or the databases disagree


def same_airport(a: dict, b: dict) -> bool:
    return (a["icao"] and a["icao"] == b["icao"]) or dist_km(a["lat"], a["lon"], b["lat"], b["lon"]) < 8


def on_the_way(origin: dict, destination: dict, lat: float, lon: float) -> bool:
    direct = dist_km(origin["lat"], origin["lon"], destination["lat"], destination["lon"])
    via = dist_km(origin["lat"], origin["lon"], lat, lon) + dist_km(lat, lon, destination["lat"], destination["lon"])
    return direct > 30 and via <= 1.3 * direct + 400


def needs_trace(entry: dict | None, f: dict, now: float) -> bool:
    if entry is None or entry["callsign"] != f["callsign"]:
        return True
    if now - entry["checked_at"] > 18 * 3600:
        return True
    if now - entry["last_seen"] > 1500 and (entry.get("last_alt") or 0) < 3000:
        return True                                        # disappeared while low: probably landed and left again
    if entry["dep"] is None:
        return entry["attempts"] < 3 or now - entry["checked_at"] > 7200
    return False


def add_routes(flights: list[dict], cache_file: Path) -> None:
    """Add `dep`, `arr`, `path` (and `sched` when unconfirmed) to each airborne flight, in place."""
    airports = Airports()
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    legs, scheduled = cache.setdefault("flights", {}), cache.setdefault("scheduled", {})
    now = time.time()
    session = requests.Session()
    traces = lookups = 0

    for f in flights:
        if f["on_ground"]:
            legs.pop(f["icao24"], None)                    # landed: the next take-off is a new flight
            continue
        entry = legs.get(f["icao24"])

        if needs_trace(entry, f, now) and traces < MAX_TRACES_PER_RUN:
            traces += 1
            attempts = entry["attempts"] + 1 if entry and entry["callsign"] == f["callsign"] else 1
            trace = fetch_trace(session, f["icao24"])
            time.sleep(PAUSE_S)
            dep = find_departure(trace, airports) if trace else None
            if dep:
                # the track must belong to the flight we see now: its end has to be reachable from here
                end = dep.pop("trace_end")
                reach_km = 50 + max(0.0, f["last_contact"] - end["t"]) * 0.3
                if dist_km(end["lat"], end["lon"], f["lat"], f["lon"]) > reach_km:
                    dep = None
            entry = {"callsign": f["callsign"], "dep": dep, "checked_at": now, "attempts": attempts}
            legs[f["icao24"]] = entry
        if entry is None:
            continue
        entry["last_seen"], entry["last_alt"] = now, f["altitude_m"]

        sched = scheduled.get(f["callsign"])
        ttl = ROUTE_TTL_S if sched and sched["legs"] else UNKNOWN_ROUTE_TTL_S
        if (sched is None or now - sched["at"] > ttl) and lookups < MAX_ROUTE_LOOKUPS_PER_RUN:
            lookups += 1
            found = fetch_scheduled(session, f["callsign"], airports)
            time.sleep(PAUSE_S)
            if found is not None:
                sched = scheduled[f["callsign"]] = {"legs": found, "at": now}
        sched_legs = sched["legs"] if sched else []

        dep = entry["dep"]
        if dep:
            f["dep"] = {**dep["airport"], "time": dep["time"]}
            f["path"] = dep["path"]
            arr = confirmed_destination(sched_legs, dep["airport"], f["lat"], f["lon"])
            if arr:
                f["arr"] = arr

    for icao24 in [k for k, e in legs.items() if now - e.get("last_seen", now) > 86400]:
        del legs[icao24]
    for cs in [k for k, s in scheduled.items() if now - s["at"] > 30 * 86400]:
        del scheduled[cs]

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache))
    air = [f for f in flights if not f["on_ground"]]
    print(f"routes: {traces} tracks and {lookups} schedules downloaded; of {len(air)} airborne flights "
          f"{sum('dep' in f for f in air)} have a measured departure, {sum('arr' in f for f in air)} a confirmed destination")
