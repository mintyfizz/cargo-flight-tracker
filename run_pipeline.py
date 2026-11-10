"""Run the SQL steps in order and export the KPI tables as JSON.

Reads the stored snapshots from RAW_DIR (default: data/raw/states). To analyse the full
history collected by the scheduled job, check out the `data` branch next to the code:

    git fetch origin data && git worktree add databranch origin/data
    RAW_DIR=databranch/states python run_pipeline.py
"""

import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
SQL_DIR = ROOT / "sql"
RAW_DIR = Path(os.getenv("RAW_DIR", ROOT / "data" / "raw" / "states")).resolve()
COVERAGE_CSV = RAW_DIR.parent / "routes" / "coverage.csv"
EXPORT_DIR = ROOT / "data" / "kpis"
COVERAGE_HEADER = "fetched_at,airborne,departure_measured,destination_confirmed\n"


def main() -> None:
    os.chdir(ROOT)  # the SQL reads reference/*.csv by relative path
    if not COVERAGE_CSV.exists():
        COVERAGE_CSV.parent.mkdir(parents=True, exist_ok=True)
        COVERAGE_CSV.write_text(COVERAGE_HEADER)

    (ROOT / "data").mkdir(exist_ok=True)
    con = duckdb.connect(str(ROOT / "data" / "cargo.duckdb"))
    con.execute("SET enable_progress_bar = false")
    con.execute("SET TimeZone = 'UTC'")
    con.execute("SET VARIABLE raw_glob = ?", [str(RAW_DIR / "date=*" / "*.json.gz")])
    con.execute("SET VARIABLE coverage_csv = ?", [str(COVERAGE_CSV)])

    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        print(f"Running {sql_file.name}")
        con.execute(sql_file.read_text())

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    kpi_tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'kpi_%' ORDER BY 1"
    ).fetchall()
    for (table,) in kpi_tables:
        con.sql(f"SELECT * FROM {table}").df().to_json(
            EXPORT_DIR / f"{table}.json", orient="records", indent=2, date_format="iso"
        )
        print(f"\n{table}")
        print(con.sql(f"SELECT * FROM {table} LIMIT 12"))

    con.close()


if __name__ == "__main__":
    main()
