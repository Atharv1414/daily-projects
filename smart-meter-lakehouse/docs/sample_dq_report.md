# Data quality and load report

## Row counts

| Table | Rows |
|---|---:|
| `bronze.readings` | 1,352,788 |
| `silver.readings` | 1,337,908 |
| `silver.quarantine` | 5,633 |
| `gold.dim_customer` | 1,172 |
| `gold.fact_halfhour` | 1,337,908 |
| `gold.fact_daily_meter` | 28,000 |

Files by status: loaded=60; late files: 0; late-arriving reads applied to earlier days: 15,330.
SCD2: 1,018 customers, 172 historical (closed) versions.

## Rule results

| Source | Rule | Severity | Failed | Checked | % |
|---|---|---|---:|---:|---:|
| customers | event_ts_invalid | error | 1 | 1,218 | 0.082 |
| customers | customer_id_missing | error | 1 | 1,218 | 0.082 |
| customers | meter_id_missing | error | 1 | 1,218 | 0.082 |
| customers | op_invalid | error | 1 | 1,218 | 0.082 |
| customers | tariff_unknown | error | 0 | 1,218 | 0.0 |
| readings | kwh_missing | error | 2,691 | 1,352,788 | 0.199 |
| readings | kwh_negative | error | 1,342 | 1,352,788 | 0.099 |
| readings | meter_unknown | error | 672 | 1,352,788 | 0.05 |
| readings | kwh_above_supply_limit | error | 660 | 1,352,788 | 0.049 |
| readings | read_at_misaligned | error | 264 | 1,352,788 | 0.02 |
| readings | read_at_unparseable | error | 0 | 1,352,788 | 0.0 |
| readings | meter_id_missing | error | 0 | 1,352,788 | 0.0 |
| readings | estimated_read | warn | 26,864 | 1,352,788 | 1.986 |
| readings | high_usage | warn | 411 | 1,352,788 | 0.03 |
