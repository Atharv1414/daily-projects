"""Declarative data-quality rules evaluated in SQL, with quarantine and per-rule metrics.

A rule is a SQL predicate that is TRUE when a row FAILS. ``error`` rules quarantine the row;
``warn`` rules only count it (and may flag it downstream). Results go to
``silver.dq_results`` so quality can be trended per batch.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str  # "error" | "warn"
    fails_when: str
    description: str


SUPPLY_LIMIT_KWH = 11.5  # 100 A x 230 V for 30 minutes
HIGH_USAGE_KWH = 5.0

READING_RULES = [
    Rule(
        "meter_id_missing",
        "error",
        "meter_id IS NULL OR trim(meter_id) = ''",
        "every read must identify a meter",
    ),
    Rule(
        "read_at_unparseable",
        "error",
        "read_ts IS NULL",
        "timestamp is neither ISO-8601 UTC nor dd/mm/yyyy HH:MM UK local",
    ),
    Rule(
        "read_at_misaligned",
        "error",
        "read_ts IS NOT NULL AND (minute(read_ts) NOT IN (0, 30) OR second(read_ts) <> 0)",
        "settlement periods start on :00 or :30",
    ),
    Rule("kwh_missing", "error", "kwh_num IS NULL", "consumption must be numeric"),
    Rule("kwh_negative", "error", "kwh_num < 0", "import meters cannot run backwards"),
    Rule(
        "kwh_above_supply_limit",
        "error",
        f"kwh_num > {SUPPLY_LIMIT_KWH}",
        "physically impossible for a 100 A domestic supply",
    ),
    Rule(
        "meter_unknown",
        "error",
        "meter_id NOT IN (SELECT meter_id FROM silver.customer_events)",
        "orphan read: meter not registered in CRM",
    ),
    Rule(
        "high_usage",
        "warn",
        f"kwh_num > {HIGH_USAGE_KWH} AND kwh_num <= {SUPPLY_LIMIT_KWH}",
        "plausible but unusual; flagged for review",
    ),
    Rule("estimated_read", "warn", "reading_type = 'E'", "estimated, not actual"),
]

CUSTOMER_RULES = [
    Rule("op_invalid", "error", "op IS NULL OR op NOT IN ('c', 'u', 'd')", "unknown CDC op"),
    Rule("event_ts_invalid", "error", "ts IS NULL", "unparseable event timestamp"),
    Rule("customer_id_missing", "error", "customer_id IS NULL", "event without a key"),
    Rule("meter_id_missing", "error", "meter_id IS NULL", "customer without a meter"),
    Rule(
        "tariff_unknown",
        "error",
        "op <> 'd' AND tariff_code NOT IN (SELECT tariff_code FROM silver.tariffs)",
        "tariff not in the tariff catalogue",
    ),
]


@dataclass
class QualityOutcome:
    checked: int
    rejected_rows: int
    failures: dict[str, int]

    @property
    def error_rate(self) -> float:
        return self.rejected_rows / self.checked if self.checked else 0.0


def evaluate(
    con: duckdb.DuckDBPyConnection,
    staging: str,
    rules: list[Rule],
    source: str,
    batch_column: str = "_batch_id",
) -> QualityOutcome:
    """Evaluate ``rules`` over the ``staging`` relation, quarantining error rows.

    Adds a boolean ``_rejected`` column to a temp table ``<staging>_checked`` that callers
    use to select the clean rows.
    """
    flags = ",\n".join(f'COALESCE({r.fails_when}, FALSE) AS "f_{r.name}"' for r in rules)
    errors = [r for r in rules if r.severity == "error"]
    rejected = " OR ".join(f'"f_{r.name}"' for r in errors) or "FALSE"
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {staging}_checked AS SELECT *, {flags} FROM {staging}"
    )
    con.execute(f"ALTER TABLE {staging}_checked ADD COLUMN _rejected BOOLEAN")
    con.execute(f"UPDATE {staging}_checked SET _rejected = ({rejected})")
    checked = con.execute(f"SELECT COUNT(*) FROM {staging}_checked").fetchone()[0]
    failures: dict[str, int] = {}
    for r in rules:
        n = con.execute(f'SELECT COUNT(*) FROM {staging}_checked WHERE "f_{r.name}"').fetchone()[0]
        failures[r.name] = n
        con.execute(
            f"""INSERT INTO silver.dq_results
                        SELECT DISTINCT {batch_column}, ?, ?, ?, ?, ? FROM {staging}_checked""",
            [source, r.name, r.severity, n, checked],
        )
        if r.severity == "error" and n:
            con.execute(
                f"""
                INSERT INTO silver.quarantine (source, rule, severity, record, _source_file,
                                               _line_no, _batch_id)
                SELECT ?, ?, 'error', CAST(to_json(s) AS VARCHAR), _source_file, _line_no,
                       {batch_column}
                FROM {staging}_checked s WHERE "f_{r.name}" """,
                [source, r.name],
            )
    rejected_rows = con.execute(
        f"SELECT COUNT(*) FROM {staging}_checked WHERE _rejected"
    ).fetchone()[0]
    return QualityOutcome(checked, rejected_rows, failures)
