"""Seeded landing-zone generator for a fictional GB electricity supplier.

Writes four source feeds in four formats, one delivery per day, with the problems real
feeds have:

* ``readings_<date>.csv``: half-hourly meter reads. Duplicates, nulls, negative and
  impossible values, unknown meters, local-time timestamps, late-arriving rows and
  corrections in the next day's file, a re-sent file, and a schema change on 1 October
  (``kwh`` renamed to ``consumption_kwh``, ``reading_type`` added).
* ``customers_<date>.jsonl``: CDC events from the CRM (create/update/delete), out of order,
  with duplicates, tariff switches, home moves and change-of-tenancy.
* ``tariffs_<date>.json``: paginated API payloads, including the 1 October price-cap change.
* ``weather_<yyyy-mm>.parquet``: daily mean temperature by region.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

REGIONS = {
    # region: (share of meters, temperature offset vs England average, postcode areas)
    "London": (0.13, 1.0, ["E", "N", "SE", "SW", "W"]),
    "South East": (0.12, 0.5, ["BN", "GU", "ME", "RH"]),
    "Eastern": (0.10, 0.0, ["CB", "CO", "IP", "NR"]),
    "Southern": (0.09, 0.6, ["SO", "PO", "RG", "OX"]),
    "South West": (0.07, 0.8, ["BS", "EX", "PL", "TQ"]),
    "Midlands East": (0.08, -0.3, ["DE", "LE", "NG"]),
    "Midlands West": (0.08, -0.3, ["B", "CV", "WV"]),
    "North West": (0.09, -0.6, ["M", "BL", "PR"]),
    "Merseyside & N Wales": (0.05, -0.4, ["L", "CH", "LL"]),
    "Yorkshire": (0.08, -0.8, ["LS", "S", "YO", "HU"]),
    "North East": (0.04, -1.2, ["NE", "SR", "DH"]),
    "South Wales": (0.03, 0.2, ["CF", "SA", "NP"]),
    "Scotland South": (0.03, -1.8, ["EH", "G", "KA"]),
    "Scotland North": (0.01, -2.6, ["AB", "IV", "DD"]),
}
TARIFF_MIX = {"FLEX-STD": 0.45, "FIX-12M-26": 0.30, "EV-NIGHT": 0.15, "TRACKER": 0.10}
TARIFF_PERIODS = [
    # code, name, unit p/kWh, off-peak p/kWh, standing p/day, valid_from, valid_to
    ("FLEX-STD", "Flexible Standard", 24.86, None, 53.68, "2026-07-01", "2026-09-30"),
    ("FIX-12M-26", "Fixed 12M (Jun 26)", 23.95, None, 51.20, "2026-06-01", None),
    ("EV-NIGHT", "EV Night Saver", 27.40, 7.50, 53.68, "2026-07-01", "2026-09-30"),
    ("TRACKER", "Tracker", 22.10, None, 49.50, "2026-07-01", "2026-09-30"),
]
TARIFF_OCT = [
    ("FLEX-STD", "Flexible Standard", 26.10, None, 54.75, "2026-10-01", None),
    ("EV-NIGHT", "EV Night Saver", 28.65, 7.80, 54.75, "2026-10-01", None),
    ("TRACKER", "Tracker", 23.40, None, 49.50, "2026-10-01", None),
]
SCHEMA_CHANGE_DATE = date(2026, 10, 1)
START_DATE = date(2026, 9, 15)

# Normalised domestic load shape over 48 half-hours (overnight trough, two daily peaks).
_HOURS = np.arange(48) / 2
SHAPE = (
    0.35
    + 0.55 * np.exp(-((_HOURS - 7.75) ** 2) / 2.0)
    + 1.00 * np.exp(-((_HOURS - 18.5) ** 2) / 4.5)
    + 0.25 * np.exp(-((_HOURS - 13) ** 2) / 8.0)
)
SHAPE = SHAPE / SHAPE.sum()


@dataclass(frozen=True)
class LandingSummary:
    meters: int
    days: int
    reading_rows: int
    customer_events: int
    files: int


@dataclass
class _Meter:
    meter_id: str
    account: str
    region: str
    postcode: str
    tariff: str
    daily_kwh: float
    heating: float


def _postcode(rng: random.Random, region: str) -> str:
    return f"{rng.choice(REGIONS[region][2])}{rng.randint(1, 28)}"


def _temperature(rng: np.random.Generator, day: date, region: str) -> float:
    seasonal = 15.5 - 0.17 * (day - START_DATE).days  # autumn cooling
    return round(seasonal + REGIONS[region][1] + rng.normal(0, 1.6), 1)


def generate_landing(
    landing: Path, meters: int = 1_000, days: int = 28, seed: int = 7
) -> LandingSummary:
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    landing.mkdir(parents=True, exist_ok=True)
    for old in landing.iterdir():
        old.unlink()
    regions = list(REGIONS)
    fleet: list[_Meter] = []
    for i in range(meters):
        region = rng.choices(regions, weights=[REGIONS[r][0] for r in regions])[0]
        tariff = rng.choices(list(TARIFF_MIX), weights=list(TARIFF_MIX.values()))[0]
        fleet.append(
            _Meter(
                f"MTR{100000 + i}",
                f"ACC{500000 + i}",
                region,
                _postcode(rng, region),
                tariff,
                float(nrng.lognormal(2.0, 0.35)),
                float(nrng.uniform(0.0, 0.08)),
            )
        )
    dates = [START_DATE + timedelta(days=d) for d in range(days)]
    temps = {(d, r): _temperature(nrng, d, r) for d in dates for r in regions}
    files = 0

    # --- weather (parquet, one file per month) -------------------------------------------
    for month in sorted({d.strftime("%Y-%m") for d in dates}):
        rows = [
            (d, r, temps[(d, r)]) for d in dates for r in regions if d.strftime("%Y-%m") == month
        ]
        table = pa.table(
            {
                "date": [r[0] for r in rows],
                "region": [r[1] for r in rows],
                "mean_temp_c": [r[2] for r in rows],
            }
        )
        pq.write_table(table, landing / f"weather_{month}.parquet")
        files += 1

    # --- tariffs (JSON API payloads) -----------------------------------------------------
    for delivered, periods in ((dates[0], TARIFF_PERIODS), (date(2026, 9, 24), TARIFF_OCT)):
        if delivered > dates[-1]:
            continue
        data = [
            {
                "tariff_code": c,
                "display_name": n,
                "unit_rate_p": u,
                "offpeak_rate_p": o,
                "offpeak_window": "00:30-05:30" if o else None,
                "standing_charge_p_day": s,
                "valid_from": f,
                "valid_to": t,
            }
            for c, n, u, o, s, f, t in periods
        ]
        payload = {
            "data": data,
            "meta": {"page": 1, "total_pages": 1, "generated_at": f"{delivered}T06:00:00Z"},
        }
        (landing / f"tariffs_{delivered}.json").write_text(json.dumps(payload, indent=1))
        files += 1

    # --- customer CDC events (JSON Lines) ------------------------------------------------
    events_total = 0
    next_account = 900000
    for di, day in enumerate(dates):
        events = []
        base = datetime.combine(day, datetime.min.time())
        if di == 0:
            for m in fleet:
                events.append(("c", m, base + timedelta(minutes=rng.randint(0, 300))))
        else:
            for m in fleet:
                roll = rng.random()
                ts = base + timedelta(minutes=rng.randint(360, 1300))
                if roll < 0.004:
                    m.tariff = rng.choice([t for t in TARIFF_MIX if t != m.tariff])
                    events.append(("u", m, ts))
                elif roll < 0.005:
                    m.postcode = _postcode(rng, m.region)
                    events.append(("u", m, ts))
                elif roll < 0.0055:  # change of tenancy: old account closes, new one opens
                    events.append(("d", _Meter(**vars(m)), ts))
                    m.account = f"ACC{next_account}"
                    next_account += 1
                    events.append(("c", m, ts + timedelta(minutes=1)))
        lines = [
            json.dumps(
                {
                    "op": op,
                    "event_ts": ts.isoformat() + "Z",
                    "source": "crm",
                    "customer": {
                        "customer_id": m.account,
                        "meter_id": m.meter_id,
                        "region": m.region,
                        "postcode_district": m.postcode,
                        "tariff_code": m.tariff,
                        "psr": m.heating > 0.075,
                    },
                }
            )
            for op, m, ts in events
        ]
        if lines and di > 0:
            lines.append(lines[0])  # duplicate delivery
        if di == 3:
            lines.append(json.dumps({"op": "x", "event_ts": "not-a-date", "customer": {}}))
        rng.shuffle(lines)  # out of order within the file
        events_total += len(lines)
        (landing / f"customers_{day}.jsonl").write_text("\n".join(lines) + "\n")
        files += 1

    # --- readings (CSV) ------------------------------------------------------------------
    total_rows = 0
    carry: dict[str, list[np.ndarray]] | None = None
    ids = np.array([m.meter_id for m in fleet])
    for di, day in enumerate(dates):
        temp = np.array([temps[(day, m.region)] for m in fleet])
        daily = np.array([m.daily_kwh for m in fleet]) * (
            1 + np.array([m.heating for m in fleet]) * np.clip(15.5 - temp, 0, None)
        )
        kwh = daily[:, None] * SHAPE[None, :] * nrng.lognormal(0, 0.25, (meters, 48))
        ev = np.array([m.tariff == "EV-NIGHT" for m in fleet]) & (nrng.random(meters) < 0.6)
        kwh[ev, 1:9] += nrng.uniform(1.0, 3.5, (int(ev.sum()), 8))
        kwh = np.round(kwh, 3)
        slots = np.array(
            [
                datetime.combine(day, datetime.min.time()) + timedelta(minutes=30 * s)
                for s in range(48)
            ]
        )
        meter_col = np.repeat(ids, 48)
        ts = np.tile(slots, meters)
        values = kwh.reshape(-1).astype(object)
        n = len(values)
        ts_text = np.array([t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in ts], dtype=object)
        local = nrng.random(n) < 0.03  # legacy head-end sends UK local time (BST = UTC+1)
        ts_text[local] = [(t + timedelta(hours=1)).strftime("%d/%m/%Y %H:%M") for t in ts[local]]
        flags = np.where(nrng.random(n) < 0.02, "E", "A").astype(object)
        values[nrng.random(n) < 0.002] = None
        neg = nrng.random(n) < 0.001
        values[neg] = -np.abs(kwh.reshape(-1)[neg])
        bursts = nrng.random(n) < 0.0003  # electric showers / heat-pump boost: rare, real
        values[bursts] = np.round(nrng.uniform(5.5, 9.0, int(bursts.sum())), 3)
        values[nrng.random(n) < 0.0005] = 25.0  # impossible for a 100A domestic supply
        meter_col = meter_col.astype(object)
        meter_col[nrng.random(n) < 0.0005] = "MTR999999"
        bad_min = nrng.random(n) < 0.0002
        ts_text[bad_min] = [
            t.replace("00:00Z", "15:00Z").replace("30:00Z", "45:00Z") for t in ts_text[bad_min]
        ]
        # 1% of today's reads arrive late (tomorrow's file); 0.2% get corrected tomorrow.
        late = nrng.random(n) < 0.01
        corr = (~late) & (nrng.random(n) < 0.002)
        keep = ~late
        cols = [meter_col[keep], ts_text[keep], values[keep], flags[keep]]
        if carry:
            cols = [np.concatenate([c, k]) for c, k in zip(cols, carry["cols"], strict=True)]
        corrected = values[corr].copy()
        corrected = np.array(
            [None if v is None else round(float(v) * 1.1, 3) for v in corrected], dtype=object
        )
        carry = {
            "cols": [
                np.concatenate([meter_col[late], meter_col[corr]]),
                np.concatenate([ts_text[late], ts_text[corr]]),
                np.concatenate([values[late], corrected]),
                np.concatenate([flags[late], flags[corr]]),
            ]
        }
        dup = nrng.random(len(cols[0])) < 0.005
        cols = [np.concatenate([c, c[dup]]) for c in cols]
        if day >= SCHEMA_CHANGE_DATE:
            table = pa.table(
                {
                    "meter_id": cols[0].tolist(),
                    "read_at": cols[1].tolist(),
                    "consumption_kwh": cols[2].tolist(),
                    "reading_type": cols[3].tolist(),
                    "quality_flag": ["OK"] * len(cols[0]),
                }
            )
        else:
            table = pa.table(
                {
                    "meter_id": cols[0].tolist(),
                    "read_at": cols[1].tolist(),
                    "kwh": cols[2].tolist(),
                    "quality_flag": np.where(cols[3] == "E", "EST", "OK").tolist(),
                }
            )
        path = landing / f"readings_{day}.csv"
        pacsv.write_csv(table, path)
        total_rows += table.num_rows
        files += 1
        if di == 5:  # the head-end re-sends a file under a new name
            (landing / f"readings_{day}_resend.csv").write_bytes(path.read_bytes())
            total_rows += table.num_rows
            files += 1
    return LandingSummary(meters, days, total_rows, events_total, files)
