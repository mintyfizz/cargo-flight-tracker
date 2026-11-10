# Europe's night belongs to cargo

A live data pipeline that tracks express cargo flights over Europe, using real aircraft positions
from the [OpenSky Network](https://opensky-network.org) API.

> **Key finding:** _coming soon_

**Live dashboard:** _coming soon_

## The question

Express parcels cross Europe overnight by air. When does the cargo network fly,
which hubs does it run through, and how much of the night sky is cargo?

## Data

- **Source:** OpenSky Network REST API, `/states/all`: live position, altitude, speed and callsign
  of every aircraft broadcasting ADS-B over the selected area.
- **Collection:** `ingest/fetch_states.py` saves one raw snapshot every 15 minutes
  (`data/raw/states/date=YYYY-MM-DD/HHMMSS.json.gz`), building a real dataset over time.
- **Reference data:** cargo airline call-sign prefixes (`reference/cargo_operators.csv`)
  and hub airport coordinates (`reference/hubs.csv`).

Data from the OpenSky Network, used for non-commercial research and education.
See [OpenSky's terms of use](https://opensky-network.org/about/terms-of-use).

## How it works

1. **Collect:** a scheduled job calls the API every 15 minutes and stores the raw responses
2. **Stage:** flatten snapshots into one row per aircraft per snapshot (`sql/01_staging.sql`)
3. **Model:** identify cargo flights, link aircraft on the ground to hubs, group snapshots into flights (`sql/02_flights.sql`)
4. **Summarise:** KPI tables (`sql/03_kpis.sql`) exported as JSON
5. **Show:** a static dashboard on GitHub Pages (`dashboard/`)

## Run it yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python ingest/fetch_states.py      # one live snapshot
python run_pipeline.py
```
