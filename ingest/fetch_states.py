"""Fetch one live snapshot of all aircraft worldwide from the OpenSky Network API.

Each run saves the raw API response, untouched, as one gzipped JSON file:
    data/raw/states/date=YYYY-MM-DD/HHMMSS.json.gz

Run it on a schedule (every 15 minutes) to build up a real dataset over days and weeks.

Works without an account (anonymous: about 400 API credits per day; this query
costs 4 credits, so every 15 minutes = 384 credits/day). With a free OpenSky
account, set OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET to get a higher limit.

API docs: https://openskynetwork.github.io/opensky-api/rest.html
"""

import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://opensky-network.org/api/states/all"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

# No bounding box = the whole world (costs 4 API credits per call)
BBOX: dict[str, float] = {}

# Where snapshots are saved (the scheduled GitHub job overrides this with RAW_DIR)
RAW_DIR = Path(os.getenv("RAW_DIR", Path(__file__).resolve().parent.parent / "data" / "raw" / "states"))


def get_token() -> str | None:
    client_id = os.getenv("OPENSKY_CLIENT_ID")
    client_secret = os.getenv("OPENSKY_CLIENT_SECRET")
    if not (client_id and client_secret):
        return None
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch() -> dict:
    headers = {"User-Agent": "cargo-flight-tracker (portfolio project)"}
    token = get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(3):
        try:
            resp = requests.get(API, params=BBOX, headers=headers, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:  # network hiccup or rate limit: wait and retry
            if attempt == 2:
                raise
            print(f"Attempt {attempt + 1} failed ({exc}), retrying in 20s")
            time.sleep(20)
    raise RuntimeError("unreachable")


def main() -> None:
    fetched_at = datetime.now(timezone.utc)
    payload = fetch()
    payload["fetched_at"] = fetched_at.isoformat()

    out_dir = RAW_DIR / f"date={fetched_at:%Y-%m-%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{fetched_at:%H%M%S}.json.gz"
    with gzip.open(out_file, "wt", encoding="utf-8") as f:
        json.dump(payload, f)

    n = len(payload.get("states") or [])
    print(f"{fetched_at:%Y-%m-%d %H:%M:%S} UTC  {n} aircraft  ->  {out_file.name}")


if __name__ == "__main__":
    main()
