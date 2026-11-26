# KPI definitions

| KPI | Definition | Formula | Target | Better when |
|---|---|---|---|---|
| Parcels | Parcels loaded for delivery. | `SUM(parcels)` | – | higher |
| First-attempt delivery | Share of parcels delivered on the first attempt. | `SUM(first_attempt_successes) / SUM(parcels)` | 92.0% | higher |
| On-time delivery | Share of parcels delivered on the first attempt within the promised window. | `SUM(on_time_parcels) / SUM(parcels)` | 88.0% | higher |
| Return to sender | Share of parcels returned to the sender after three failed attempts. | `SUM(returned) / SUM(parcels)` | 1.00% | lower |
| Cost per parcel | Route cost (driver, van, energy) plus redelivery and return cost, per parcel delivered. | `SUM(total_cost) / SUM(delivered)` | £2.05 | lower |
| Parcels per driver hour | Parcels handled per paid driver hour. | `SUM(parcels) / SUM(driver_hours)` | 13.0 | higher |
| Van utilisation | Parcels loaded as a share of van capacity. Above 92% vans run out of time and service falls. | `SUM(planned_stops) / SUM(capacity)` | 75.0% | higher (red above 92.0%) |
| CO2e per parcel (kg) | Tailpipe and grid emissions per parcel, from km driven and vehicle emission factors. | `SUM(co2_kg) / SUM(parcels)` | 0.150 | lower |
