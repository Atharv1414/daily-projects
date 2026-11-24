import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from .clean import Cleaned, clean
from .config import Config
from .extract import SOURCES, Raw, Source
from .http import Fetcher

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    source: str
    status: str
    pages: int = 0
    failed_pages: int = 0
    retries: int = 0
    loaded: int = 0
    rejected: int = 0
    duplicates: int = 0
    message: str | None = None


class Store(Protocol):
    def start_run(self, source: str) -> int: ...
    def finish_run(self, run_id: int, status: str, message: str | None, **counts) -> None: ...
    def quarantine(self, run_id: int, rejected: list) -> None: ...
    def load(self, run_id: int, records: list, today) -> None: ...


def extract(source: Source) -> tuple[list[Raw], str | None]:
    """Whatever was read before a failure is kept, along with the problem."""
    raws: list[Raw] = []
    try:
        for raw in source.records():
            raws.append(raw)
    except Exception as exc:
        log.exception("%s: extraction stopped", source.name)
        return raws, f"{type(exc).__name__}: {exc}"
    if source.truncated:
        return raws, "page limit reached"
    if source.failed_pages:
        return raws, f"{len(source.failed_pages)} pages could not be fetched"
    return raws, None


def judge(cleaned: Cleaned, problem: str | None, max_reject_rate: float) -> tuple[str, str | None]:
    if not cleaned.records:
        return "failed", problem or "no valid records"
    if cleaned.reject_rate > max_reject_rate:
        return "failed", f"{cleaned.reject_rate:.0%} of records failed validation; nothing loaded"
    return ("partial", problem) if problem else ("succeeded", None)


def run_source(name: str, config: Config, fetcher: Fetcher, store: Store | None) -> RunReport:
    """Run one source. `store=None` is a dry run. Never raises for a problem with the source."""
    settings = config.sources[name]
    run_id = store.start_run(name) if store else 0
    retries_before = fetcher.retries
    report = RunReport(name, "failed")
    try:
        source = SOURCES[name](fetcher, str(settings.url), settings.max_pages)
        raws, problem = extract(source)
        cleaned = clean(name, raws)
        status, message = judge(cleaned, problem, config.max_reject_rate)
        report.pages, report.failed_pages = source.pages, len(source.failed_pages)
        report.retries = fetcher.retries - retries_before
        report.rejected, report.duplicates = len(cleaned.rejected), cleaned.duplicates
        if store:
            store.quarantine(run_id, cleaned.rejected)
        if status != "failed":
            if store:
                store.load(run_id, cleaned.records, datetime.now(UTC).date())
            report.loaded = len(cleaned.records)
        report.status, report.message = status, message
    except Exception as exc:
        log.exception("%s: run failed", name)
        report.status, report.message = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        if store:
            counts = {k: v for k, v in asdict(report).items() if isinstance(v, int)}
            store.finish_run(run_id, report.status, report.message, **counts)
    return report
