#pragma once

#include <cstdint>
#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "jobsearch/segment.hpp"
#include "jobsearch/types.hpp"

namespace jobsearch {

/// Immutable set of deleted (closed or replaced) documents for one segment.
using DeleteSet = std::vector<bool>;

/// A segment plus the deletions that applied to it when the snapshot was taken.
struct SegmentView {
    std::shared_ptr<const Segment> segment;
    std::shared_ptr<const DeleteSet> deleted;  // never null; sized to segment->doc_count()
    std::uint32_t deleted_count = 0;

    [[nodiscard]] bool is_live(DocId doc) const { return !(*deleted)[doc]; }
    [[nodiscard]] std::uint32_t live_docs() const { return segment->doc_count() - deleted_count; }
};

/// A consistent, point-in-time view of the index. Searches hold one for their whole run, so a
/// concurrent refresh, delete or merge can never change results half-way through a query.
struct Snapshot {
    std::uint64_t generation = 0;
    std::vector<SegmentView> segments;

    [[nodiscard]] std::uint64_t live_docs() const;
    [[nodiscard]] std::uint64_t total_docs() const;
};

struct IndexOptions {
    /// Buffered adverts are turned into a segment once this many are waiting.
    std::size_t flush_threshold = 4096;
    /// Merge the smallest segments once there are more than this many.
    std::size_t max_segments = 8;
    /// How many segments a single merge combines.
    std::size_t merge_width = 4;
    /// A segment whose deleted share is above this is rewritten on the next refresh.
    double max_deleted_ratio = 0.3;
};

struct IndexStats {
    std::uint64_t generation = 0;
    std::size_t segments = 0;
    std::uint64_t live_docs = 0;
    std::uint64_t deleted_docs = 0;
    std::size_t buffered_docs = 0;
    std::size_t postings_bytes = 0;
    std::uint64_t flushes = 0;
    std::uint64_t merges = 0;
};

/// The writable index. All mutations are serialised by one writer mutex; readers only take
/// a very short lock to copy the current snapshot pointer and never block on a merge.
///
/// Like Lucene, writes are near-real-time: `upsert` and `remove` take effect for readers on
/// the next `refresh()`. Deletes of already-indexed adverts are visible immediately.
class Index {
  public:
    explicit Index(IndexOptions options = {});

    /// Adds or replaces an advert by id. Returns true if it replaced an existing one.
    bool upsert(JobAd job);
    /// Removes an advert (job filled or withdrawn). Returns false if the id is unknown.
    bool remove(std::string_view job_id);
    /// Flushes the buffer into a new segment and runs the merge policy.
    void refresh();
    /// Forces everything into a single segment (useful before shipping a read-only index).
    void force_merge();

    [[nodiscard]] std::shared_ptr<const Snapshot> snapshot() const;
    [[nodiscard]] IndexStats stats() const;
    [[nodiscard]] std::optional<JobAd> get(std::string_view job_id) const;

    /// Persists every segment and an atomic MANIFEST; old segment files are cleaned up.
    void save(const std::filesystem::path& dir);
    [[nodiscard]] static std::unique_ptr<Index> open(const std::filesystem::path& dir,
                                                     IndexOptions options = {});

  private:
    struct Location {
        std::uint64_t segment_id = 0;
        DocId doc = 0;
    };

    void publish_locked(std::vector<SegmentView> segments);
    void flush_locked();
    void merge_locked(std::vector<std::size_t> victims);
    void maybe_merge_locked();
    void reindex_locations_locked(const SegmentView& view);
    [[nodiscard]] bool delete_indexed_locked(std::string_view job_id);

    IndexOptions options_;
    mutable std::mutex write_mu_;
    mutable std::mutex snapshot_mu_;
    std::shared_ptr<const Snapshot> current_;
    std::vector<JobAd> buffer_;
    std::unordered_map<std::string, std::size_t> buffered_;
    std::unordered_map<std::string, Location> locations_;
    std::uint64_t next_segment_id_ = 1;
    std::uint64_t flushes_ = 0;
    std::uint64_t merges_ = 0;
};

}  // namespace jobsearch
