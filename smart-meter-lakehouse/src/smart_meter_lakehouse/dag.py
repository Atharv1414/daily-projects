"""A small Airflow-style DAG runner: dependency resolution, retries, run metadata, lineage."""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import duckdb

from smart_meter_lakehouse.errors import DagError, TransientSourceError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Task:
    name: str
    fn: Callable[[dict[str, Any]], int | None]
    deps: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    retries: int | None = None  # None = use the runner default


@dataclass
class TaskResult:
    name: str
    status: str  # success | failed | skipped
    attempts: int = 0
    rows: int | None = None
    error: str | None = None
    seconds: float = 0.0


@dataclass
class RunResult:
    run_id: str
    status: str
    tasks: dict[str, TaskResult] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "success"


class DAG:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tasks: dict[str, Task] = {}

    def add(self, task: Task) -> Task:
        if task.name in self.tasks:
            raise DagError(f"duplicate task {task.name!r}")
        self.tasks[task.name] = task
        return task

    def topological_order(self) -> list[str]:
        """Kahn's algorithm; ties broken by insertion order so runs are deterministic."""
        for t in self.tasks.values():
            missing = [d for d in t.deps if d not in self.tasks]
            if missing:
                raise DagError(f"task {t.name!r} depends on unknown {missing}")
        indegree = {n: len(t.deps) for n, t in self.tasks.items()}
        children: dict[str, list[str]] = {n: [] for n in self.tasks}
        for t in self.tasks.values():
            for d in t.deps:
                children[d].append(t.name)
        queue = deque(n for n in self.tasks if indegree[n] == 0)
        order = []
        while queue:
            n = queue.popleft()
            order.append(n)
            for c in children[n]:
                indegree[c] -= 1
                if indegree[c] == 0:
                    queue.append(c)
        if len(order) != len(self.tasks):
            cyclic = sorted(n for n, d in indegree.items() if d > 0)
            raise DagError(f"cycle detected among {cyclic}")
        return order

    def to_mermaid(self) -> str:
        lines = ["flowchart LR"]
        for t in self.tasks.values():
            lines += [f"    {d} --> {t.name}" for d in t.deps] or [f"    {t.name}"]
        return "\n".join(lines)


class Runner:
    """Runs a DAG in topological order, recording every attempt in ``meta.*`` tables.

    Only ``TransientSourceError`` is retried (with exponential backoff); anything else is a
    bug or a data problem and fails fast. Downstream tasks of a failure are skipped.
    """

    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        max_retries: int = 3,
        backoff_s: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.con = con
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.sleep = sleep

    def run(self, dag: DAG, context: dict[str, Any], through: date | None = None) -> RunResult:
        order = dag.topological_order()
        run_id = context.setdefault(
            "run_id", datetime.now().strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:6]
        )
        self.con.execute(
            "INSERT INTO meta.dag_runs VALUES (?, ?, 'running', ?, NULL)",
            [run_id, through, datetime.now()],
        )
        result = RunResult(run_id, "success")
        for name in order:
            task = dag.tasks[name]
            failed_upstream = [d for d in task.deps if result.tasks[d].status != "success"]
            if failed_upstream:
                result.tasks[name] = TaskResult(
                    name, "skipped", error=f"upstream failed: {failed_upstream}"
                )
                self._record(run_id, result.tasks[name], datetime.now())
                continue
            result.tasks[name] = self._run_task(run_id, task, context)
            if result.tasks[name].status == "failed":
                result.status = "failed"
        self.con.execute(
            "UPDATE meta.dag_runs SET status = ?, finished_at = ? WHERE run_id = ?",
            [result.status, datetime.now(), run_id],
        )
        return result

    def _run_task(self, run_id: str, task: Task, context: dict[str, Any]) -> TaskResult:
        limit = self.max_retries if task.retries is None else task.retries
        started = datetime.now()
        t0 = time.perf_counter()
        attempt = 0
        while True:
            attempt += 1
            try:
                rows = task.fn(context)
            except TransientSourceError as exc:
                if attempt <= limit:
                    delay = self.backoff_s * 2 ** (attempt - 1)
                    log.warning(
                        "%s transient failure (attempt %s), retrying in %.2fs: %s",
                        task.name,
                        attempt,
                        delay,
                        exc,
                    )
                    self.sleep(delay)
                    continue
                res = TaskResult(task.name, "failed", attempt, error=str(exc))
                break
            except Exception as exc:  # noqa: BLE001 - recorded and surfaced in the result
                log.error("%s failed: %s", task.name, exc)
                res = TaskResult(task.name, "failed", attempt, error=f"{type(exc).__name__}: {exc}")
                break
            res = TaskResult(task.name, "success", attempt, rows=rows)
            break
        res.seconds = round(time.perf_counter() - t0, 3)
        self._record(run_id, res, started)
        if res.status == "success":
            for src in task.inputs or ("-",):
                for dst in task.outputs or ("-",):
                    self.con.execute(
                        "INSERT INTO meta.lineage VALUES (?, ?, ?, ?)",
                        [run_id, task.name, src, dst],
                    )
        return res

    def _record(self, run_id: str, res: TaskResult, started: datetime) -> None:
        self.con.execute(
            "INSERT INTO meta.task_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                res.name,
                res.status,
                res.attempts,
                res.rows,
                res.error,
                started,
                datetime.now(),
            ],
        )
