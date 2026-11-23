"""The stream processor: poll → parse → de-duplicate → window → fire → checkpoint.

Processing guarantees:

* **Event-time correctness.** Windows are defined on device event time, not arrival time.
  Watermarks (bounded out-of-orderness, minimum across partitions) decide when a window is
  complete.
* **Bounded state.** Fired windows, closed sessions and de-duplication ids older than the
  lateness horizon are evicted.
* **Exactly-once effect.** Outputs are buffered between checkpoints and committed together
  with the consumer offsets and a snapshot of every operator. A crash anywhere loses only
  uncommitted work, which is recomputed identically on restart.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from dataclasses import dataclass

from .alerts import RebufferAlertDetector
from .config import Settings
from .errors import SimulatedCrash
from .events import DeadLetter, PlayerEvent, parse_record
from .log import LogRecord, PartitionedLog
from .observability import RunStats, log_event
from .operators import Deduplicator, SessionWindowOperator, WindowAggregator
from .sink import DuckDBSink, OutputBuffer
from .windows import WatermarkTracker, hopping, tumbling

logger = logging.getLogger("streaming_qoe_pipeline.pipeline")

# Arrival delay histogram buckets (upper bounds, ms) for the delivery-latency profile.
DELAY_BUCKETS = (1_000, 5_000, 30_000, 90_000, 300_000, 1_800_000)


def delay_bucket(delay_ms: int) -> str:
    for bound in DELAY_BUCKETS:
        if delay_ms <= bound:
            return f"<= {bound // 1000}s"
    return f"> {DELAY_BUCKETS[-1] // 1000}s"


@dataclass
class RunResult:
    run_id: str
    polls: int
    checkpoints: int
    finished: bool
    stats: dict[str, object]


class StreamProcessor:
    def __init__(
        self,
        settings: Settings,
        log: PartitionedLog,
        sink: DuckDBSink,
        crash_after_polls: int | None = None,
    ) -> None:
        self.s = settings
        self.log = log
        self.sink = sink
        self.crash_after_polls = crash_after_polls
        self.stats = RunStats()
        self.delay_histogram: Counter[str] = Counter()
        self.outputs = OutputBuffer()
        self.checkpoint_id = 0

        self.watermarks = WatermarkTracker(settings.partitions, settings.max_out_of_orderness_ms)
        horizon = settings.allowed_lateness_ms + max(
            settings.hopping_size_ms, settings.session_gap_ms, settings.tumbling_window_ms
        )
        self.dedup = Deduplicator(horizon)
        self.minute = WindowAggregator(
            "qoe_minute",
            lambda ts: tumbling(ts, settings.tumbling_window_ms),
            lambda e: (e.cdn, e.region, e.device),
            ("cdn", "region", "device"),
            settings.allowed_lateness_ms,
            track_sessions=True,
        )
        self.hopping = WindowAggregator(
            "qoe_cdn_region_5m",
            lambda ts: hopping(ts, settings.hopping_size_ms, settings.hopping_slide_ms),
            lambda e: (e.cdn, e.region),
            ("cdn", "region"),
            settings.allowed_lateness_ms,
        )
        self.sessions = SessionWindowOperator(settings.session_gap_ms)
        self.detector = RebufferAlertDetector(
            settings.alert_z_threshold,
            settings.alert_min_ratio,
            settings.alert_min_watch_ms,
            settings.alert_warmup_windows,
            settings.alert_ewma_alpha,
        )
        self.offsets = dict.fromkeys(range(settings.partitions), 0)
        self._restore()

    # ------------------------------------------------------------------ state

    def snapshot(self) -> dict[str, object]:
        return {
            "watermarks": self.watermarks.snapshot(),
            "dedup": self.dedup.snapshot(),
            "minute": self.minute.snapshot(),
            "hopping": self.hopping.snapshot(),
            "sessions": self.sessions.snapshot(),
            "detector": self.detector.snapshot(),
        }

    def _restore(self) -> None:
        checkpoint = self.sink.load_checkpoint(self.s.consumer_group)
        if checkpoint is None:
            return
        st = checkpoint.state
        self.watermarks.restore(st["watermarks"])  # type: ignore[arg-type]
        self.dedup.restore(st["dedup"])  # type: ignore[arg-type]
        self.minute.restore(st["minute"])  # type: ignore[arg-type]
        self.hopping.restore(st["hopping"])  # type: ignore[arg-type]
        self.sessions.restore(st["sessions"])  # type: ignore[arg-type]
        self.detector.restore(st["detector"])  # type: ignore[arg-type]
        self.offsets.update(checkpoint.offsets)
        self.checkpoint_id = checkpoint.checkpoint_id
        log_event(
            logger,
            "restored checkpoint",
            checkpoint_id=checkpoint.checkpoint_id,
            watermark_ms=checkpoint.watermark_ms,
            offsets=checkpoint.offsets,
        )

    # ------------------------------------------------------------- processing

    def _handle(self, record: LogRecord) -> None:
        self.stats.incr("records_read")
        parsed = parse_record(record.value, record.partition, record.offset)
        if isinstance(parsed, DeadLetter):
            self._dead(parsed)
            return
        if parsed.ts > record.arrival_ms + self.s.max_future_skew_ms:
            # A device clock set in the future would drag the watermark forward and make
            # everyone else's data "late", so it is quarantined rather than processed.
            self._dead(
                DeadLetter(
                    partition=record.partition,
                    offset=record.offset,
                    reason="future_timestamp",
                    detail=f"event time {parsed.ts - record.arrival_ms} ms after arrival",
                    raw=record.value[:2000],
                )
            )
            return
        if self.dedup.is_duplicate(parsed):
            self.stats.incr("duplicates_dropped")
            return
        self.delay_histogram[delay_bucket(record.arrival_ms - parsed.ts)] += 1
        self.watermarks.observe(record.partition, parsed.ts)
        self._route(parsed)

    def _route(self, e: PlayerEvent) -> None:
        watermark = self.watermarks.current
        self.stats.incr("events_processed")
        self.stats.incr(f"schema_v{e.schema_version}")
        for operator in (self.minute, self.hopping, self.sessions):
            late = operator.process(e, watermark)
            if late is not None:
                self.stats.incr(f"late_{operator.name}")
                self.outputs.add("late_events", [late.row()])

    def _dead(self, dl: DeadLetter) -> None:
        self.stats.incr("dead_letters")
        self.stats.incr(f"dlq_{dl.reason}")
        self.outputs.add("dead_letters", [dl.model_dump()])

    def _fire(self) -> None:
        watermark = self.watermarks.current
        self.outputs.add("qoe_minute", self.minute.fire(watermark))
        hop_rows = self.hopping.fire(watermark)
        self.outputs.add("qoe_cdn_region_5m", hop_rows)
        alerts = [a for a in (self.detector.observe(r) for r in hop_rows) if a is not None]
        self.outputs.add("alerts", alerts)
        self.stats.incr("alerts", len(alerts))
        self.outputs.add("sessions", self.sessions.fire(watermark))
        self.stats.incr("dedup_evicted", self.dedup.evict(watermark))

    def _checkpoint(self) -> None:
        self.checkpoint_id += 1
        started = time.perf_counter()
        size = self.sink.commit(
            self.s.consumer_group,
            self.checkpoint_id,
            self.watermarks.current,
            self.offsets,
            self.snapshot(),
            self.outputs,
        )
        self.stats.checkpoint_seconds.append(time.perf_counter() - started)
        self.stats.checkpoint_bytes.append(size)
        self.outputs.clear()

    def poll_once(self) -> int:
        """Read one batch from every partition; returns the number of records read."""
        total = 0
        for partition in range(self.s.partitions):
            batch = self.log.read(
                partition, self.offsets[partition], self.s.poll_records_per_partition
            )
            for record in batch:
                self._handle(record)
                self.offsets[partition] = record.offset + 1
            total += len(batch)
        return total

    def run(self, drain: bool = True, max_polls: int | None = None) -> RunResult:
        """Process until the log is exhausted (and drain open windows) or ``max_polls``."""
        run_id = uuid.uuid4().hex[:12]
        polls = 0
        checkpoints_before = self.checkpoint_id
        end_offsets = self.log.end_offsets()
        finished = False
        while max_polls is None or polls < max_polls:
            read = self.poll_once()
            polls += 1
            if drain:
                for partition, end in end_offsets.items():
                    if self.offsets[partition] >= end:
                        self.watermarks.mark_idle(partition)
            self.watermarks.advance()
            if read == 0:
                if drain:
                    self.watermarks.finish()
                    self._fire()
                    self._checkpoint()
                finished = True
                break
            self._fire()
            if self.crash_after_polls is not None and polls >= self.crash_after_polls:
                raise SimulatedCrash(f"simulated crash after poll {polls}")
            if polls % self.s.checkpoint_every_polls == 0:
                self._checkpoint()
        else:
            self._checkpoint()

        summary = self.stats.summary()
        summary["delay_histogram"] = dict(self.delay_histogram)
        summary["open_windows"] = self.minute.open_windows + self.hopping.open_windows
        summary["open_sessions"] = self.sessions.open_sessions
        summary["dedup_ids"] = len(self.dedup)
        self.sink.record_run(
            run_id,
            self.s.consumer_group,
            self.stats.started_at,
            "finished" if finished else "paused",
            summary,
        )
        log_event(logger, "run complete", run_id=run_id, polls=polls, **summary)
        return RunResult(run_id, polls, self.checkpoint_id - checkpoints_before, finished, summary)
