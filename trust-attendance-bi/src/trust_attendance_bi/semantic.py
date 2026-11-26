"""Semantic layer: governed metric definitions, an aggregate navigator and a SQL compiler.

Analysts ask for metrics by dimensions ("persistent absence by school and term"). The
navigator picks the smallest table that can answer correctly:

* additive metrics (session counts and rates built from them) can come from any aggregate
  that holds every requested dimension;
* pupil metrics (head counts, persistent and severe absence) need one row per pupil, so
  they come from ``agg_pupil_term`` or, for daily or weekly slices, from the fact table.

Row-level security is applied here too, so no caller can forget it.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import duckdb
import pandas as pd


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    kind: str  # "ratio", "count", "pupil_count" or "pupil_share"
    expression: str  # over the summed components (see COMPONENTS)
    description: str
    unit: str = "%"

    @property
    def needs_pupils(self) -> bool:
        return self.kind.startswith("pupil")


COMPONENTS = ("possible", "present", "authorised", "unauthorised", "missing", "amended", "marks")

METRICS: dict[str, Metric] = {
    m.name: m
    for m in (
        Metric(
            "attendance_rate",
            "Attendance",
            "ratio",
            "100.0 * present / nullif(possible, 0)",
            "Sessions attended (including late before close and approved off-site) as a "
            "share of possible sessions.",
        ),
        Metric(
            "absence_rate",
            "Overall absence",
            "ratio",
            "100.0 * (authorised + unauthorised) / nullif(possible, 0)",
            "Sessions missed for any reason as a share of possible sessions.",
        ),
        Metric(
            "authorised_absence_rate",
            "Authorised absence",
            "ratio",
            "100.0 * authorised / nullif(possible, 0)",
            "Illness, appointments, religious observance, suspensions and other authorised.",
        ),
        Metric(
            "unauthorised_absence_rate",
            "Unauthorised absence",
            "ratio",
            "100.0 * unauthorised / nullif(possible, 0)",
            "Unauthorised, holidays not agreed, late after registers closed and no reason.",
        ),
        Metric(
            "sessions_possible",
            "Possible sessions",
            "count",
            "possible",
            "Half-day sessions a pupil could have attended.",
            unit="sessions",
        ),
        Metric(
            "sessions_missed",
            "Sessions missed",
            "count",
            "authorised + unauthorised",
            "Half-day sessions missed for any reason.",
            unit="sessions",
        ),
        Metric(
            "amended_share",
            "Marks amended",
            "ratio",
            "100.0 * amended / nullif(marks, 0)",
            "Share of register marks changed after first entry (a data-quality signal).",
        ),
        Metric(
            "pupils",
            "Pupils",
            "pupil_count",
            "count(*)",
            "Distinct pupils on roll in the slice. Not additive across rows.",
            unit="pupils",
        ),
        Metric(
            "persistent_absence_rate",
            "Persistent absence",
            "pupil_share",
            "100.0 * avg(((authorised + unauthorised) >= 0.1 * possible)::INTEGER)",
            "Share of pupils who missed 10% or more of their possible sessions (DfE "
            "definition). Measured per pupil over the whole slice, so it is not additive.",
        ),
        Metric(
            "severe_absence_rate",
            "Severe absence",
            "pupil_share",
            "100.0 * avg(((authorised + unauthorised) >= 0.5 * possible)::INTEGER)",
            "Share of pupils who missed 50% or more of their possible sessions.",
        ),
    )
}

# dimension name -> column
DIMENSIONS: dict[str, str] = {
    "school": "school_id",
    "phase": "phase",
    "year_group": "year_group",
    "term": "term",
    "month": "month_start",
    "week": "week_start",
    "date": "date",
    "weekday": "weekday",
    "code": "code",
    "sex": "sex",
    "fsm": "fsm",
    "sen": "sen",
}

_GROUP = {"school", "phase", "year_group", "term", "sex", "fsm", "sen"}


@dataclass(frozen=True)
class Table:
    name: str
    dims: frozenset[str]
    pupil_grain: bool  # one row per pupil (or finer): distinct pupils can be counted


TABLES: tuple[Table, ...] = (
    Table("agg_group_term", frozenset(_GROUP), False),
    Table("agg_group_month", frozenset(_GROUP | {"month"}), False),
    Table("agg_group_week", frozenset(_GROUP | {"week"}), False),
    Table("agg_pupil_term", frozenset(_GROUP), True),
    Table("fact_attendance_session", frozenset(DIMENSIONS), True),
)


class QueryError(ValueError):
    """The request names an unknown metric or dimension, or no table can answer it."""


class AccessDenied(PermissionError):
    """The caller asked for data outside their row-level security scope."""


@dataclass(frozen=True)
class Principal:
    """Who is asking. Trust staff see everything; heads see their school; year leads see one
    year group in one school."""

    role: str  # "trust", "head" or "year_lead"
    school_id: str | None = None
    year_group: str | None = None

    @classmethod
    def parse(cls, text: str) -> Principal:
        parts = text.split(":")
        if parts[0] == "trust" and len(parts) == 1:
            return cls("trust")
        if parts[0] == "head" and len(parts) == 2:
            return cls("head", parts[1])
        if parts[0] == "year_lead" and len(parts) == 3:
            return cls("year_lead", parts[1], parts[2])
        raise QueryError("role must be trust, head:<school> or year_lead:<school>:<year>")

    def scope(self) -> dict[str, str]:
        scope: dict[str, str] = {}
        if self.role in {"head", "year_lead"}:
            scope["school"] = self.school_id or ""
        if self.role == "year_lead":
            scope["year_group"] = self.year_group or ""
        return scope


TRUST = Principal("trust")


@dataclass
class Plan:
    table: str
    reason: str
    sql: str
    params: list
    rows_in_table: int = 0
    seconds: float = 0.0


@dataclass
class MetricQuery:
    metrics: list[str]
    by: list[str] = field(default_factory=list)
    filters: dict[str, object] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.metrics:
            raise QueryError("ask for at least one metric")
        unknown = [m for m in self.metrics if m not in METRICS]
        unknown += [d for d in [*self.by, *self.filters] if d not in DIMENSIONS]
        if unknown:
            raise QueryError(f"unknown metric or dimension: {', '.join(unknown)}")
        if len(set(self.by)) != len(self.by):
            raise QueryError("a dimension is listed twice")


class SemanticLayer:
    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.con = con
        self._sizes = {
            t.name: con.execute(f"SELECT count(*) FROM {t.name}").fetchone()[0] for t in TABLES
        }

    # ---- planning ----------------------------------------------------------------------

    def choose(self, query: MetricQuery, principal: Principal = TRUST) -> tuple[Table, str]:
        needed = set(query.by) | set(query.filters) | set(principal.scope())
        needs_pupils = any(METRICS[m].needs_pupils for m in query.metrics)
        fits = [t for t in TABLES if needed <= t.dims and (t.pupil_grain or not needs_pupils)]
        if not fits:
            raise QueryError(f"no table holds {sorted(needed)} at the grain these metrics need")
        best = min(fits, key=lambda t: self._sizes[t.name])
        why = f"smallest of {len(fits)} tables with {sorted(needed) or 'no dimensions'}" + (
            "; pupil-level metrics need one row per pupil" if needs_pupils else ""
        )
        return best, why

    def compile(
        self, query: MetricQuery, principal: Principal = TRUST, table_name: str | None = None
    ) -> Plan:
        query.validate()
        filters = self._apply_scope(query.filters, principal)
        if table_name is None:
            table, reason = self.choose(MetricQuery(query.metrics, query.by, filters), principal)
        else:  # forced, e.g. to prove every table gives the same answer, or to benchmark
            table = next(t for t in TABLES if t.name == table_name)
            reason = "forced"
        where, params = _where(filters)
        dims = [DIMENSIONS[d] for d in query.by]
        sums = _component_sums(table)
        select_dims = "".join(f"{d}, " for d in dims)
        group = f" GROUP BY {', '.join(dims)}" if dims else ""
        needs_pupils = any(METRICS[m].needs_pupils for m in query.metrics)
        outputs = ", ".join(
            f"round({METRICS[m].expression}, 2) AS {m}"
            if METRICS[m].kind in {"ratio", "pupil_share"}
            else f"{METRICS[m].expression} AS {m}"
            for m in query.metrics
        )
        if needs_pupils:
            # Step 1: one row per pupil (and requested slice). Step 2: classify and count.
            inner = (
                f"SELECT pupil_id, {select_dims}{sums} FROM {table.name}{where} "
                f"GROUP BY pupil_id{''.join(f', {d}' for d in dims)}"
            )
            outer_sums = ", ".join(f"sum({c}) AS {c}" for c in COMPONENTS)  # already summed
            sql = (
                f"WITH per_pupil AS ({inner}), totals AS (SELECT {select_dims}{outer_sums}, "
                f"count(*) AS n_pupils, "
                f"avg(((authorised + unauthorised) >= 0.1 * possible)::INTEGER) AS pa, "
                f"avg(((authorised + unauthorised) >= 0.5 * possible)::INTEGER) AS sa "
                f"FROM per_pupil{group}) "
                f"SELECT {select_dims}{_pupil_outputs(query.metrics)} FROM totals"
            )
        else:
            inner = f"SELECT {select_dims}{sums} FROM {table.name}{where}{group}"
            sql = f"SELECT {select_dims}{outputs} FROM ({inner})"
        if dims:
            sql += f" ORDER BY {', '.join(_order(d) for d in dims)}"
        return Plan(table.name, reason, sql, params, self._sizes[table.name])

    def query(
        self, query: MetricQuery, principal: Principal = TRUST, table_name: str | None = None
    ) -> tuple[pd.DataFrame, Plan]:
        plan = self.compile(query, principal, table_name)
        t0 = time.perf_counter()
        df = self.con.execute(plan.sql, plan.params).df()
        plan.seconds = time.perf_counter() - t0
        df = df.rename(columns={v: k for k, v in DIMENSIONS.items() if k in query.by})
        return df, plan

    # ---- security ----------------------------------------------------------------------

    @staticmethod
    def _apply_scope(filters: Mapping[str, object], principal: Principal) -> dict[str, object]:
        merged = dict(filters)
        for dim, allowed in principal.scope().items():
            asked = merged.get(dim)
            asked_values = set(asked) if isinstance(asked, list | tuple | set) else {asked}
            if asked is not None and asked_values != {allowed}:
                raise AccessDenied(f"{principal.role} may only see {dim} = {allowed}")
            merged[dim] = allowed
        return merged


def _component_sums(table: Table) -> str:
    # Aggregates store a mark count; the fact has one row per mark.
    return ", ".join(
        "count(*) AS marks"
        if c == "marks" and table.name == "fact_attendance_session"
        else f"sum({c}) AS {c}"
        for c in COMPONENTS
    )


def _order(column: str) -> str:
    if column == "year_group":  # Reception first, then Years 1 to 11 in number order
        return "CASE year_group WHEN 'R' THEN 0 ELSE try_cast(year_group AS INTEGER) END"
    return column


def _pupil_outputs(metrics: Iterable[str]) -> str:
    out = []
    for m in metrics:
        metric = METRICS[m]
        if m == "pupils":
            out.append("n_pupils AS pupils")
        elif m == "persistent_absence_rate":
            out.append("round(100.0 * pa, 2) AS persistent_absence_rate")
        elif m == "severe_absence_rate":
            out.append("round(100.0 * sa, 2) AS severe_absence_rate")
        elif metric.kind == "ratio":
            out.append(f"round({metric.expression}, 2) AS {m}")
        else:
            out.append(f"{metric.expression} AS {m}")
    return ", ".join(out)


def _where(filters: Mapping[str, object]) -> tuple[str, list]:
    clauses, params = [], []
    for dim, value in filters.items():
        column = DIMENSIONS[dim]
        if isinstance(value, list | tuple | set):
            values = list(value)
            if not values:
                raise QueryError(f"empty filter list for {dim}")
            clauses.append(f"{column} IN ({', '.join('?' for _ in values)})")
            params.extend(values)
        else:
            clauses.append(f"{column} = ?")
            params.append(value)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params
