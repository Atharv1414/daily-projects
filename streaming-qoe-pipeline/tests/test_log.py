from pathlib import Path

import pytest

from streaming_qoe_pipeline.errors import LogCorruptionError
from streaming_qoe_pipeline.log import PartitionedLog, partition_for


def test_append_and_read_across_segment_boundaries(tmp_path: Path) -> None:
    log = PartitionedLog(tmp_path, partitions=2, segment_size=10)
    log.write_partition(0, [(i, "k", f"v{i}") for i in range(25)])
    assert len(log.segments(0)) == 3
    assert log.end_offset(0) == 25
    batch = log.read(0, from_offset=8, max_records=5)
    assert [r.offset for r in batch] == [8, 9, 10, 11, 12]
    assert batch[-1].value == "v12"
    assert log.read(0, 25, 10) == []
    assert log.end_offsets() == {0: 25, 1: 0}


def test_appends_continue_offsets(tmp_path: Path) -> None:
    log = PartitionedLog(tmp_path, partitions=1, segment_size=4)
    log.write_partition(0, [(1, "k", "a"), (2, "k", "b"), (3, "k", "c")])
    log.write_partition(0, [(4, "k", "d"), (5, "k", "e")])
    assert [r.value for r in log.read(0, 0, 10)] == ["a", "b", "c", "d", "e"]


def test_partitioner_is_stable_and_in_range() -> None:
    keys = [f"s-{i:016x}" for i in range(1_000)]
    parts = [partition_for(k, 4) for k in keys]
    assert parts == [partition_for(k, 4) for k in keys]
    assert set(parts) == {0, 1, 2, 3}


def test_corrupt_envelope_raises(tmp_path: Path) -> None:
    log = PartitionedLog(tmp_path, partitions=1, segment_size=100)
    log.write_partition(0, [(1, "k", "ok")])
    segment = log.segments(0)[0][1]
    segment.write_text(segment.read_text() + "not json\n")
    with pytest.raises(LogCorruptionError):
        log.read(0, 0, 10)
