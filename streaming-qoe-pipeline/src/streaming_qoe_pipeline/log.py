"""A Kafka-style partitioned, append-only log on the local filesystem.

Layout::

    <log_dir>/partition-<n>/<base_offset:020d>.jsonl

Each line is an envelope ``{"offset", "arrival_ms", "key", "value"}`` where ``value`` is the
raw payload string exactly as the client sent it (it may be malformed). Records are keyed by
session id, so all events of a session land on one partition and keep their arrival order.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .errors import LogCorruptionError


@dataclass(frozen=True, slots=True)
class LogRecord:
    partition: int
    offset: int
    arrival_ms: int
    key: str
    value: str


def partition_for(key: str, partitions: int) -> int:
    """Stable partitioner (CRC32), so a key always maps to the same partition across runs."""
    return zlib.crc32(key.encode()) % partitions


class PartitionedLog:
    def __init__(self, root: Path, partitions: int, segment_size: int = 20_000) -> None:
        self.root = root
        self.partitions = partitions
        self.segment_size = segment_size

    def _dir(self, partition: int) -> Path:
        return self.root / f"partition-{partition}"

    def segments(self, partition: int) -> list[tuple[int, Path]]:
        directory = self._dir(partition)
        if not directory.exists():
            return []
        return sorted((int(p.stem), p) for p in directory.glob("*.jsonl"))

    def end_offset(self, partition: int) -> int:
        """Offset that the next appended record would get (the log-end offset)."""
        segs = self.segments(partition)
        if not segs:
            return 0
        base, path = segs[-1]
        with path.open("rb") as fh:
            return base + sum(1 for _ in fh)

    def end_offsets(self) -> dict[int, int]:
        return {p: self.end_offset(p) for p in range(self.partitions)}

    def write_partition(self, partition: int, records: list[tuple[int, str, str]]) -> int:
        """Append ``(arrival_ms, key, value)`` tuples to one partition, rolling segments."""
        directory = self._dir(partition)
        directory.mkdir(parents=True, exist_ok=True)
        offset = self.end_offset(partition)
        handle = None
        try:
            for arrival_ms, key, value in records:
                if handle is None or offset % self.segment_size == 0:
                    if handle is not None:
                        handle.close()
                    base = offset - offset % self.segment_size
                    handle = (directory / f"{base:020d}.jsonl").open("a", encoding="utf-8")
                envelope = {"offset": offset, "arrival_ms": arrival_ms, "key": key, "value": value}
                handle.write(json.dumps(envelope, separators=(",", ":")) + "\n")
                offset += 1
        finally:
            if handle is not None:
                handle.close()
        return offset

    def read(self, partition: int, from_offset: int, max_records: int) -> list[LogRecord]:
        """Read up to ``max_records`` starting at ``from_offset`` (seeks to the right segment)."""
        out: list[LogRecord] = []
        for record in self._iter_from(partition, from_offset):
            out.append(record)
            if len(out) >= max_records:
                break
        return out

    def _iter_from(self, partition: int, from_offset: int) -> Iterator[LogRecord]:
        for base, path in self.segments(partition):
            if base + self.segment_size <= from_offset:
                continue
            with path.open(encoding="utf-8") as fh:
                for index, line in enumerate(fh):
                    offset = base + index
                    if offset < from_offset:
                        continue
                    try:
                        env = json.loads(line)
                        record = LogRecord(
                            partition,
                            int(env["offset"]),
                            int(env["arrival_ms"]),
                            env["key"],
                            env["value"],
                        )
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                        raise LogCorruptionError(f"partition {partition} offset {offset}") from exc
                    if record.offset != offset:
                        raise LogCorruptionError(
                            f"partition {partition}: expected offset {offset}, got {record.offset}"
                        )
                    yield record
