# Data

`trust-bi build` writes the synthetic MIS exports to `data/raw/` (about 9 MB, so they are generated, not committed) and the DuckDB warehouse to `data/warehouse.duckdb`. The generator is `src/trust_attendance_bi/generate.py` (seed 26), so every build is identical.
