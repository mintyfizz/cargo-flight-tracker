"""Run the SQL steps in order and export the KPI tables for the dashboard."""

from pathlib import Path

import duckdb

ROOT = Path(__file__).parent
SQL_DIR = ROOT / "sql"
EXPORT_DIR = ROOT / "dashboard" / "data"


def main() -> None:
    con = duckdb.connect(str(ROOT / "data" / "cargo.duckdb"))
    con.execute("SET enable_progress_bar = false")

    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        print(f"Running {sql_file.name}")
        con.execute(sql_file.read_text())

    kpi_tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'kpi_%'"
    ).fetchall()
    for (table,) in kpi_tables:
        con.sql(f"SELECT * FROM {table}").df().to_json(
            EXPORT_DIR / f"{table}.json", orient="records", indent=2
        )
        print(f"Exported {table}.json")

    con.close()


if __name__ == "__main__":
    main()
