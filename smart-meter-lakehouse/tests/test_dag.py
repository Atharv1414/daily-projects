import pytest

from smart_meter_lakehouse.dag import DAG, Runner, Task
from smart_meter_lakehouse.errors import DagError, TransientSourceError
from smart_meter_lakehouse.warehouse import connect


@pytest.fixture
def mem():
    c = connect(":memory:")
    yield c
    c.close()


def noop(ctx):
    return 1


def test_topological_order_respects_dependencies():
    dag = DAG("t")
    dag.add(Task("c", noop, ("a", "b")))
    dag.add(Task("a", noop))
    dag.add(Task("b", noop, ("a",)))
    order = dag.topological_order()
    assert order.index("a") < order.index("b") < order.index("c")


def test_cycle_detected():
    dag = DAG("t")
    dag.add(Task("a", noop, ("b",)))
    dag.add(Task("b", noop, ("a",)))
    with pytest.raises(DagError, match="cycle"):
        dag.topological_order()


def test_unknown_dependency_and_duplicates():
    dag = DAG("t")
    dag.add(Task("a", noop, ("ghost",)))
    with pytest.raises(DagError, match="unknown"):
        dag.topological_order()
    with pytest.raises(DagError, match="duplicate"):
        dag.add(Task("a", noop))


def test_transient_errors_retry_with_exponential_backoff(mem):
    calls, sleeps = [], []

    def flaky(ctx):
        calls.append(1)
        if len(calls) < 3:
            raise TransientSourceError("503")
        return 7

    dag = DAG("t")
    dag.add(Task("flaky", flaky))
    result = Runner(mem, max_retries=3, backoff_s=0.5, sleep=sleeps.append).run(dag, {})
    assert result.ok and result.tasks["flaky"].attempts == 3 and result.tasks["flaky"].rows == 7
    assert sleeps == [0.5, 1.0]


def test_retries_exhausted_fails_and_skips_downstream(mem):
    def always(ctx):
        raise TransientSourceError("down")

    dag = DAG("t")
    dag.add(Task("src", always, retries=2))
    dag.add(Task("child", noop, ("src",)))
    result = Runner(mem, sleep=lambda s: None).run(dag, {})
    assert result.status == "failed"
    assert result.tasks["src"].attempts == 3
    assert result.tasks["child"].status == "skipped"
    rows = mem.execute("SELECT task, status FROM meta.task_runs ORDER BY task").fetchall()
    assert rows == [("child", "skipped"), ("src", "failed")]


def test_non_transient_error_fails_fast(mem):
    def bug(ctx):
        raise ValueError("bad")

    dag = DAG("t")
    dag.add(Task("bug", bug))
    result = Runner(mem, sleep=lambda s: None).run(dag, {})
    assert result.tasks["bug"].attempts == 1 and "ValueError" in result.tasks["bug"].error


def test_lineage_and_mermaid(mem):
    dag = DAG("t")
    dag.add(Task("a", noop, inputs=("x",), outputs=("y", "z")))
    dag.add(Task("b", noop, ("a",)))
    Runner(mem).run(dag, {"run_id": "r1"})
    assert (
        mem.execute(
            "SELECT COUNT(*) FROM meta.lineage WHERE run_id = 'r1' AND task = 'a'"
        ).fetchone()[0]
        == 2
    )
    assert "a --> b" in dag.to_mermaid()
