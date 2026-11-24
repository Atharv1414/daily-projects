#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "historian/manifest.hpp"
#include "historian/memtable.hpp"
#include "historian/segment.hpp"
#include "historian/types.hpp"
#include "historian/wal.hpp"

namespace historian {

struct StoreOptions {
    std::size_t flush_samples = 500'000;  ///< memtable size that triggers a flush
    bool sync_wal = true;                 ///< fsync every batch before acknowledging it
    CodecChoice codec = CodecChoice::Auto;
};

struct RecoveryReport {
    std::uint64_t samples_replayed = 0;
    bool torn_tail = false;
    std::size_t orphans_removed = 0;
};

/// Aggregate of one time bucket [start, start + width).
struct Bucket {
    TimestampMs start = 0;
    std::uint64_t count = 0;
    double min = 0.0;
    double max = 0.0;
    double sum = 0.0;
    double last = 0.0;
    [[nodiscard]] double mean() const { return sum / static_cast<double>(count); }
};

struct QueryStats {
    std::size_t blocks_pruned = 0;      ///< outside the time range
    std::size_t blocks_from_index = 0;  ///< answered from index statistics alone
    std::size_t blocks_decoded = 0;
};

struct CompactionOptions {
    bool full = false;                         ///< merge everything, not just a similar-sized run
    std::optional<TimestampMs> expire_before;  ///< drop samples older than this
};

struct CompactionReport {
    std::size_t segments_in = 0;
    std::uint64_t samples_in = 0;
    std::uint64_t samples_out = 0;
    std::uint64_t bytes_in = 0;
    std::uint64_t bytes_out = 0;
};

struct StoreStats {
    std::size_t series = 0;
    std::size_t segments = 0;
    std::uint64_t segment_samples = 0;
    std::uint64_t segment_bytes = 0;
    std::size_t memtable_samples = 0;
    std::size_t blocks = 0;
    std::size_t scaled_blocks = 0;  ///< blocks using ValueCodec::ScaledDelta
};

/// Single-writer, multi-reader time-series store.
///
/// Appends hit the WAL, then the memtable. Full memtables become immutable segments.
/// Queries take a snapshot under a short shared lock and then read without any lock.
class Store {
  public:
    [[nodiscard]] static Result<std::unique_ptr<Store>> open(std::filesystem::path directory,
                                                             StoreOptions options = {});

    /// Durable (with sync_wal) and atomic per batch once it returns success.
    [[nodiscard]] Status append(std::span<const Point> batch);
    [[nodiscard]] Status flush();
    [[nodiscard]] Result<CompactionReport> compact(CompactionOptions options = {});

    /// Samples with from <= ts < to, in time order, one per timestamp.
    [[nodiscard]] Result<std::vector<Sample>> scan(std::string_view series, TimestampMs from,
                                                   TimestampMs to) const;
    /// Non-empty epoch-aligned buckets over [from, to).
    [[nodiscard]] Result<std::vector<Bucket>> aggregate(std::string_view series, TimestampMs from,
                                                        TimestampMs to, std::int64_t width,
                                                        QueryStats* stats = nullptr) const;
    [[nodiscard]] std::vector<std::string> series() const;
    [[nodiscard]] Result<StoreStats> stats() const;
    /// Re-reads every block and checks it against its checksum and index statistics.
    [[nodiscard]] Status verify() const;
    [[nodiscard]] const RecoveryReport& recovery() const noexcept { return recovery_; }

  private:
    using SegmentPtr = std::shared_ptr<const Segment>;
    Store(std::filesystem::path directory, StoreOptions options, FileDescriptor lock)
        : directory_(std::move(directory)), options_(options), lock_(std::move(lock)) {}

    [[nodiscard]] Status recover();
    [[nodiscard]] Status flush_locked();
    [[nodiscard]] std::vector<SegmentPtr> snapshot(std::string_view series, TimestampMs from,
                                                   TimestampMs to,
                                                   std::vector<Sample>& recent) const;
    [[nodiscard]] std::filesystem::path segment_path(std::uint64_t id) const;
    [[nodiscard]] std::filesystem::path wal_path(std::uint64_t id) const;

    std::filesystem::path directory_;
    StoreOptions options_;
    FileDescriptor lock_;
    RecoveryReport recovery_;

    std::mutex compaction_mutex_;  // always taken before mutex_
    mutable std::shared_mutex mutex_;
    Manifest manifest_;
    std::vector<SegmentPtr> segments_;  // same order as manifest_.segments
    Memtable memtable_;
    std::optional<WalWriter> wal_;
    std::vector<std::uint64_t> live_wals_;
};

/// Merges runs ordered oldest to newest; on equal timestamps the newest run wins.
[[nodiscard]] std::vector<Sample> merge_runs(std::vector<std::vector<Sample>> runs);

}  // namespace historian
