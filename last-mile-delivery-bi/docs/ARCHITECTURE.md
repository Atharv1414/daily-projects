# Architecture

## Model

```text
                 dim_date      dim_service
                    │               │
dim_depot ──┬── fact_route_day ◄── fact_delivery ──┬── dim_route
            │   (route × day)      (one per parcel) │
            │        │                              │
         dim_route  dim_driver · dim_vehicle ───────┘
```

| Table | Grain | Key measures |
|---|---|---|
| `fact_delivery` | one parcel | attempts, first-attempt success, delivered, on time, failure reason, redelivery cost |
| `fact_route_day` | one route on one operating day | planned stops, van capacity, km, driver hours, labour, vehicle cost, CO2e |

Dimensions: `dim_date` (integer `YYYYMMDD` key, ISO week, peak flag), `dim_depot`, `dim_route`
(area type), `dim_driver` (employment type, tenure), `dim_vehicle` (fuel type, capacity) and
`dim_service` (promise).

## Design decisions

**Two facts, not one.** Cost, distance and capacity happen once per van per day. Service
outcomes happen once per parcel. Storing route cost on every parcel row would force an
arbitrary allocation, and summing it would be wrong.

**Drill-across, not join-across.** `v_kpi_depot_day` aggregates each fact separately to the
shared depot × day grain and then joins the results. Joining the two facts row-to-row first
would repeat each route's cost once per parcel (fan-out). A test proves that the view's cost
total equals the fact totals. A quality check catches a route day that has no parcels, because
the inner join would silently drop its cost.

**Additive components, ratios at query time.** The drill-across view stores only additive
counts and sums. Every KPI in `metrics.py` is `SUM(numerator) / SUM(denominator)`, so the
network figure is volume-weighted. It is never an average of depot or daily percentages. A
test checks this against a manual weighted average.

**One definition per KPI.** The KPI registry is the single source for the dashboard, the CLI
and `docs/KPI_DEFINITIONS.md`, so the documentation cannot drift from the code.

**RAG with a ceiling.** Van utilisation is "higher is better" up to a point. Above 92%, drivers
run out of time, so the KPI carries a `ceiling` that turns it red. That matches the
utilisation-band analysis.

**Static, offline dashboard.** Plotly figures are written as HTML with `plotly.min.js` saved
once beside the pages. There is no server, no CDN and no credentials: the folder can be
emailed, put on SharePoint or served by any web server. The depot filter uses Plotly
`updatemenus`. Drill-down uses plain links to pre-rendered depot pages.

**Constraints in the database.** Primary keys, foreign keys and CHECK constraints are declared
in `schema.sql` and enforced by DuckDB. Tables load in dependency order.

## Trade-offs and limitations

- The data is synthetic. Effect sizes are set in `data_generator.py` and documented there.
- Dimensions are Type 1 (current state). A production model would track driver employment
  type and depot changes as SCD Type 2.
- The dashboard is rebuilt in batch. For intra-day monitoring, the same views could back a
  Streamlit or Power BI model on a scheduled refresh.
- On-time is measured against the delivery date promised by each service level. Time-of-day
  windows are not modelled.
