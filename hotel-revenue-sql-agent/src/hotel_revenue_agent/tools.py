"""Tool definitions: Pydantic-validated inputs, JSON schemas for Claude, and handlers."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hotel_revenue_agent.database import ALLOWED_TABLES, Warehouse
from hotel_revenue_agent.errors import ToolError, ToolNotAllowedError
from hotel_revenue_agent.kpis import CONVENTIONS, KPI_GLOSSARY


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoInput(_Strict):
    pass


class TableInput(_Strict):
    table: str = Field(description="Table name, e.g. 'bookings'.", max_length=64)

    @field_validator("table")
    @classmethod
    def known_table(cls, v: str) -> str:
        if v.lower() not in ALLOWED_TABLES:
            raise ValueError(f"unknown table; choose one of {sorted(ALLOWED_TABLES)}")
        return v.lower()


class SampleInput(TableInput):
    n: int = Field(default=5, ge=1, le=10, description="Number of random rows (1-10).")


class SQLInput(_Strict):
    sql: str = Field(
        description="A single read-only SQLite SELECT statement.", min_length=1, max_length=5_000
    )


class RunSQLInput(SQLInput):
    purpose: str = Field(
        default="", max_length=300, description="One line on what this query is meant to answer."
    )


class GlossaryInput(_Strict):
    metric: str | None = Field(
        default=None, max_length=40, description="KPI name such as 'revpar'; omit for all KPIs."
    )


class ReportInput(_Strict):
    title: str = Field(min_length=3, max_length=120)
    markdown: str = Field(
        min_length=10,
        max_length=20_000,
        description="Report body in Markdown, including the SQL used.",
    )


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[Any], Any]
    side_effect: bool = False

    def spec(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        schema.setdefault("properties", {})
        return {"name": self.name, "description": self.description, "input_schema": schema}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "report"


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool], allowlist: Iterable[str] | None = None) -> None:
        self._tools = {t.name: t for t in tools}
        self.allowlist = frozenset(allowlist) if allowlist is not None else frozenset(self._tools)
        unknown = self.allowlist - self._tools.keys()
        if unknown:
            raise ValueError(f"allowlist names unknown tools: {sorted(unknown)}")

    def specs(self) -> list[dict[str, Any]]:
        return [self._tools[n].spec() for n in sorted(self.allowlist)]

    def get(self, name: str) -> Tool:
        if name not in self.allowlist:
            raise ToolNotAllowedError(
                f"Tool {name!r} is not available.",
                hint=f"Use one of: {', '.join(sorted(self.allowlist))}.",
            )
        return self._tools[name]

    def validate(self, name: str, raw: Any) -> tuple[Tool, BaseModel]:
        tool = self.get(name)
        try:
            args = tool.input_model.model_validate(raw if isinstance(raw, dict) else {})
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors()
            )
            raise ToolError(
                f"Invalid input for {name}: {problems}", hint="Check the tool's input schema."
            ) from exc
        return tool, args


def build_tools(warehouse: Warehouse, reports_dir: Path) -> list[Tool]:
    def list_tables(_: NoInput) -> Any:
        return {"tables": warehouse.list_tables(), "conventions": CONVENTIONS}

    def describe_table(args: TableInput) -> Any:
        return warehouse.describe_table(args.table)

    def sample_rows(args: SampleInput) -> Any:
        return warehouse.sample_rows(args.table, args.n).to_payload()

    def validate_sql(args: SQLInput) -> Any:
        return {"valid": True, "plan": warehouse.explain(args.sql)}

    def run_sql(args: RunSQLInput) -> Any:
        result = warehouse.query(args.sql)
        payload = result.to_payload()
        if result.truncated:
            payload["note"] = f"Only the first {warehouse.max_rows} rows are shown; aggregate."
        if result.row_count == 0:
            payload["note"] = "Query returned no rows; check filters and date formats."
        return payload

    def kpi_glossary(args: GlossaryInput) -> Any:
        if args.metric is None:
            return {"kpis": KPI_GLOSSARY, "conventions": CONVENTIONS}
        key = args.metric.lower().replace(" ", "_")
        if key not in KPI_GLOSSARY:
            raise ToolError(
                f"Unknown KPI {args.metric!r}.",
                hint=f"Known KPIs: {', '.join(sorted(KPI_GLOSSARY))}.",
            )
        return {key: KPI_GLOSSARY[key], "conventions": CONVENTIONS}

    def save_report(args: ReportInput) -> Any:
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = reports_dir / f"{stamp}-{uuid.uuid4().hex[:6]}-{_slug(args.title)}.md"
        path.write_text(f"# {args.title}\n\n{args.markdown}\n", encoding="utf-8")
        return {"saved": True, "path": str(path.name)}

    return [
        Tool(
            "list_tables",
            "List the warehouse tables with row counts, descriptions and "
            "date/money conventions. Call this first.",
            NoInput,
            list_tables,
        ),
        Tool(
            "describe_table",
            "Column names, types and nullability for one table.",
            TableInput,
            describe_table,
        ),
        Tool(
            "sample_rows",
            "Up to 10 random rows from a table, to see real value formats.",
            SampleInput,
            sample_rows,
        ),
        Tool(
            "kpi_glossary",
            "Canonical hotel KPI definitions (ADR, RevPAR, occupancy, "
            "cancellation rate...). Use before computing any KPI.",
            GlossaryInput,
            kpi_glossary,
        ),
        Tool(
            "validate_sql",
            "Compile a SELECT and return its query plan without running it.",
            SQLInput,
            validate_sql,
        ),
        Tool(
            "run_sql",
            "Run one read-only SELECT. Results are capped; aggregate in SQL.",
            RunSQLInput,
            run_sql,
        ),
        Tool(
            "save_report",
            "Save a Markdown report to the shared reports folder. Has side "
            "effects, so a human must approve it.",
            ReportInput,
            save_report,
            side_effect=True,
        ),
    ]


def result_block(tool_use_id: str, payload: Any, is_error: bool = False) -> dict[str, Any]:
    """Wrap a tool result. Data is labelled untrusted so the model treats it as data."""
    if is_error:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": str(payload),
            "is_error": True,
        }
    body = json.dumps({"untrusted_data": True, "result": payload}, default=str)
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": body}
