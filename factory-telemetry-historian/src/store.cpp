#include "historian/store.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <map>
#include <set>

namespace historian {

namespace {

constexpr std::size_t kMaxSeriesName = 256;

std::int64_t floor_to(TimestampMs ts, std::int64_t width) {
    const std::int64_t remainder = ts % width;
    return ts - (remainder < 0 ? remainder + width : remainder);
}

/// Extracts N from "<prefix>N<suffix>".
std::optional<std::uint64_t> parse_id(const std::string& name, std::string_view prefix,
                                      std::string_view suffix) {
    if (!name.starts_with(prefix) || !name.ends_with(suffix) ||
        name.size() <= prefix.size() + suffix.size()) {
        return std::nullopt;
    }
    std::uint64_t id = 0;
    const char* first = name.data() + prefix.size();
    const char* last = name.data() + (name.size() - suffix.size());
    const auto [end, error] = std::from_chars(first, last, id);
    if (error != std::errc{} || end != last) {
        return std::nullopt;
    }
    return id;
}

/// Accumulates samples and whole blocks into time buckets.
class BucketAccumulator {
  public:
    explicit BucketAccumulator(std::int64_t width) : width_(width) {}

    void add(const Sample& s) { merge(s.ts, s.ts, 1, s.value, s.value, s.value, s.value); }
    void add(const BlockMeta& b) {
        merge(b.min_ts, b.max_ts, b.count, b.min, b.max, b.sum, b.last);
    }
    [[nodiscard]] std::vector<Bucket> take() const {
        std::vector<Bucket> out;
        out.reserve(buckets_.size());
        for (const auto& [start, entry] : buckets_) {
            out.push_back(entry.bucket);
        }
        return out;
    }

  private:
    struct Entry {
        Bucket bucket;
        TimestampMs last_ts = 0;
    };
    void merge(TimestampMs first_ts, TimestampMs last_ts, std::uint64_t count, double min,
               double max, double sum, double last) {
        const auto start = floor_to(first_ts, width_);
        const auto [it, inserted] = buckets_.try_emplace(start);
        Entry& entry = it->second;
        Bucket& b = entry.bucket;
        if (inserted) {
            b = {start, count, min, max, sum, last};
            entry.last_ts = last_ts;
            return;
        }
        b.count += count;
        b.min = std::min(b.min, min);
        b.max = std::max(b.max, max);
        b.sum += sum;
        if (last_ts >= entry.last_ts) {
            b.last = last;
            entry.last_ts = last_ts;
        }
    }
    std::int64_t width_;
    std::map<TimestampMs, Entry> buckets_;
};

struct BlockRef {
    std::size_t rank;  // position of the segment: higher is newer
    const Segment* segment;
    const BlockMeta* meta;
};

Status validate(const Point& p) {
    if (p.series.empty() || p.series.size() > kMaxSeriesName) {
        return Error{ErrorCode::InvalidArgument, "series name must be 1-256 bytes"};
    }
    if (!std::isfinite(p.sample.value)) {
        return Error{ErrorCode::InvalidArgument, p.series + ": value must be finite"};
    }
    return {};
}

}  // namespace

std::vector<Sample> merge_runs(std::vector<std::vector<Sample>> runs) {
    std::vector<Sample> merged;
    for (auto& run : runs) {
        if (merged.empty()) {
            merged = std::move(run);
        } else {
            merged.insert(merged.end(), run.begin(), run.end());
        }
    }
    const auto out_of_order = [](const Sample& a, const Sample& b) { return a.ts >= b.ts; };
    if (std::ranges::adjacent_find(merged, out_of_order) == merged.end()) {
        return merged;  // strictly increasing: the common, non-overlapping case
    }
    std::ranges::stable_sort(merged, {}, &Sample::ts);
    std::size_t kept = 0;
    for (std::size_t i = 0; i < merged.size(); ++i) {
        // Stable sort keeps run order within a timestamp, so the last duplicate is newest.
        if (i + 1 == merged.size() || merged[i + 1].ts != merged[i].ts) {
            merged[kept++] = merged[i];
        }
    }
    merged.resize(kept);
    return merged;
}

std::filesystem::path Store::segment_path(std::uint64_t id) const {
    return directory_ / ("seg-" + std::to_string(id) + ".hsg");
}

std::filesystem::path Store::wal_path(std::uint64_t id) const {
    return directory_ / ("wal-" + std::to_string(id) + ".log");
}

Result<std::unique_ptr<Store>> Store::open(std::filesystem::path directory, StoreOptions options) {
    std::error_code ec;
    std::filesystem::create_directories(directory, ec);
    if (ec) {
        return Error{ErrorCode::Io, "create " + directory.string() + ": " + ec.message()};
    }
    auto lock = lock_file(directory / "LOCK");
    if (!lock) {
        return lock.error();
    }
    std::unique_ptr<Store> store(new Store(std::move(directory), options, std::move(lock).value()));
    if (auto s = store->recover(); !s.ok()) {
        return s.error();
    }
    return store;
}

Status Store::recover() {
    auto manifest = Manifest::load(directory_);
    if (!manifest) {
        return manifest.error();
    }
    manifest_ = std::move(manifest).value();
    for (const auto id : manifest_.segments) {
        auto segment = Segment::open(id, segment_path(id));
        if (!segment) {
            return segment.error();
        }
        segments_.push_back(std::move(segment).value());
    }

    const std::set<std::uint64_t> live(manifest_.segments.begin(), manifest_.segments.end());
    std::set<std::uint64_t> wals;
    std::vector<std::filesystem::path> orphans;
    for (const auto& entry : std::filesystem::directory_iterator(directory_)) {
        const auto name = entry.path().filename().string();
        if (const auto seg = parse_id(name, "seg-", ".hsg")) {
            if (!live.contains(*seg)) {
                orphans.push_back(entry.path());
            }
            manifest_.next_id = std::max(manifest_.next_id, *seg + 1);
        } else if (const auto wal = parse_id(name, "wal-", ".log")) {
            if (*wal < manifest_.wal_floor) {
                orphans.push_back(entry.path());
            } else {
                wals.insert(*wal);
            }
            manifest_.next_id = std::max(manifest_.next_id, *wal + 1);
        } else if (name.ends_with(".tmp")) {
            orphans.push_back(entry.path());
        }
    }
    for (const auto& path : orphans) {
        std::error_code ignored;  // a leftover that cannot be removed is harmless
        recovery_.orphans_removed += std::filesystem::remove(path, ignored) ? 1U : 0U;
    }

    for (const auto id : wals) {
        const auto replay = replay_wal(wal_path(id));
        if (!replay) {
            return replay.error();
        }
        if (recovery_.torn_tail && !replay.value().batches.empty()) {
            // Only the newest WAL with data may be torn by a crash. Acknowledged batches
            // after a damaged record mean lost data, which must not pass silently.
            return Error{ErrorCode::Corrupt, "WAL damaged before its last record"};
        }
        for (const auto& batch : replay.value().batches) {
            for (const Point& p : batch) {
                memtable_.insert(p.series, p.sample);
                ++recovery_.samples_replayed;
            }
        }
        recovery_.torn_tail = recovery_.torn_tail || replay.value().torn_tail;
        live_wals_.push_back(id);
    }
    return flush_locked();  // recovered data becomes a segment and a fresh WAL starts
}

Status Store::append(std::span<const Point> batch) {
    if (batch.empty()) {
        return {};
    }
    for (const Point& p : batch) {
        if (auto s = validate(p); !s.ok()) {
            return s;
        }
    }
    const std::unique_lock lock(mutex_);
    if (auto s = wal_->append(batch); !s.ok()) {
        return s;
    }
    for (const Point& p : batch) {
        memtable_.insert(p.series, p.sample);
    }
    return memtable_.size() >= options_.flush_samples ? flush_locked() : Status{};
}

Status Store::flush() {
    const std::unique_lock lock(mutex_);
    return memtable_.size() == 0 ? Status{} : flush_locked();
}

// Order matters: segment file, new WAL, then the manifest commit. A crash before the commit
// leaves the old WAL authoritative; a crash after it leaves only deletable leftovers.
Status Store::flush_locked() {
    Manifest next = manifest_;
    SegmentPtr segment;
    if (memtable_.size() > 0) {
        SegmentBuilder builder(options_.codec);
        for (const auto& [name, samples] : memtable_.series()) {
            builder.add_series(name, samples);
        }
        const std::uint64_t id = next.next_id++;
        if (auto s = builder.write(segment_path(id)); !s.ok()) {
            return s;
        }
        auto opened = Segment::open(id, segment_path(id));
        if (!opened) {
            return opened.error();
        }
        segment = std::move(opened).value();
        next.segments.push_back(id);
    }
    const std::uint64_t wal_id = next.next_id++;
    manifest_.next_id = next.next_id;  // never reuse an id, even if the commit below fails
    auto wal = WalWriter::create(wal_path(wal_id), options_.sync_wal);
    if (!wal) {
        return wal.error();
    }
    next.wal_floor = wal_id;
    if (auto s = next.save(directory_); !s.ok()) {
        return s;
    }
    manifest_ = std::move(next);
    if (segment) {
        segments_.push_back(std::move(segment));
    }
    memtable_.clear();
    wal_.emplace(std::move(wal).value());
    for (const auto id : live_wals_) {
        std::error_code ignored;
        std::filesystem::remove(wal_path(id), ignored);
    }
    live_wals_ = {wal_id};
    return {};
}

std::vector<Store::SegmentPtr> Store::snapshot(std::string_view series, TimestampMs from,
                                               TimestampMs to, std::vector<Sample>& recent) const {
    const std::shared_lock lock(mutex_);
    recent = memtable_.range(series, from, to);
    return segments_;
}

Result<std::vector<Sample>> Store::scan(std::string_view series, TimestampMs from,
                                        TimestampMs to) const {
    std::vector<Sample> recent;
    const auto segments = snapshot(series, from, to, recent);
    std::vector<std::vector<Sample>> runs;
    for (const auto& segment : segments) {
        for (const BlockMeta& block : segment->blocks(series)) {
            if (block.max_ts < from || block.min_ts >= to) {
                continue;
            }
            auto samples = segment->read(block);
            if (!samples) {
                return samples.error();
            }
            runs.push_back(std::move(samples).value());
        }
    }
    runs.push_back(std::move(recent));
    auto merged = merge_runs(std::move(runs));
    std::erase_if(merged, [&](const Sample& s) { return s.ts < from || s.ts >= to; });
    return merged;
}

Result<std::vector<Bucket>> Store::aggregate(std::string_view series, TimestampMs from,
                                             TimestampMs to, std::int64_t width,
                                             QueryStats* stats) const {
    if (width <= 0) {
        return Error{ErrorCode::InvalidArgument, "bucket width must be positive"};
    }
    QueryStats local;
    std::vector<Sample> recent;
    const auto segments = snapshot(series, from, to, recent);
    std::vector<BlockRef> blocks;
    for (std::size_t rank = 0; rank < segments.size(); ++rank) {
        for (const BlockMeta& block : segments[rank]->blocks(series)) {
            if (block.max_ts < from || block.min_ts >= to) {
                ++local.blocks_pruned;
            } else {
                blocks.push_back({rank, segments[rank].get(), &block});
            }
        }
    }
    std::ranges::sort(blocks, {}, [](const BlockRef& b) { return b.meta->min_ts; });

    BucketAccumulator buckets(width);
    std::size_t next_recent = 0;  // recent[next_recent..] not yet consumed
    for (std::size_t i = 0; i < blocks.size();) {
        // Grow a cluster of blocks whose time ranges overlap. Inside one, a timestamp may
        // appear more than once, so index statistics would double count.
        std::size_t end = i + 1;
        TimestampMs cluster_max = blocks[i].meta->max_ts;
        while (end < blocks.size() && blocks[end].meta->min_ts <= cluster_max) {
            cluster_max = std::max(cluster_max, blocks[end].meta->max_ts);
            ++end;
        }
        const TimestampMs cluster_min = blocks[i].meta->min_ts;
        while (next_recent < recent.size() && recent[next_recent].ts < cluster_min) {
            buckets.add(recent[next_recent++]);
        }
        std::vector<Sample> overlapping;
        while (next_recent < recent.size() && recent[next_recent].ts <= cluster_max) {
            overlapping.push_back(recent[next_recent++]);
        }
        const BlockMeta& only = *blocks[i].meta;
        const bool whole = end - i == 1 && overlapping.empty() && only.min_ts >= from &&
                           only.max_ts < to &&
                           floor_to(only.min_ts, width) == floor_to(only.max_ts, width);
        if (whole) {
            buckets.add(only);
            ++local.blocks_from_index;
        } else {
            const auto first = blocks.begin() + static_cast<std::ptrdiff_t>(i);
            const auto last = blocks.begin() + static_cast<std::ptrdiff_t>(end);
            std::sort(first, last,
                      [](const BlockRef& a, const BlockRef& b) { return a.rank < b.rank; });
            std::vector<std::vector<Sample>> runs;
            for (auto it = first; it != last; ++it) {
                auto samples = it->segment->read(*it->meta);
                if (!samples) {
                    return samples.error();
                }
                ++local.blocks_decoded;
                runs.push_back(std::move(samples).value());
            }
            runs.push_back(std::move(overlapping));
            for (const Sample& s : merge_runs(std::move(runs))) {
                if (s.ts >= from && s.ts < to) {
                    buckets.add(s);
                }
            }
        }
        i = end;
    }
    for (; next_recent < recent.size(); ++next_recent) {
        buckets.add(recent[next_recent]);
    }
    if (stats != nullptr) {
        *stats = local;
    }
    return buckets.take();
}

namespace {

/// Longest run of adjacent segments within a factor of four in size. Only adjacent segments
/// may merge, otherwise an older value could end up ranked above a newer one.
std::pair<std::size_t, std::size_t> pick_run(
    std::span<const std::shared_ptr<const Segment>> segments, bool full) {
    if (full) {
        return {0, segments.size()};
    }
    std::pair<std::size_t, std::size_t> best{0, 0};
    for (std::size_t begin = 0; begin < segments.size(); ++begin) {
        std::uint64_t smallest = segments[begin]->file_bytes();
        std::uint64_t largest = smallest;
        std::size_t end = begin + 1;
        for (; end < segments.size(); ++end) {
            smallest = std::min(smallest, segments[end]->file_bytes());
            largest = std::max(largest, segments[end]->file_bytes());
            if (largest > 4 * smallest) {
                break;
            }
        }
        if (end - begin > best.second - best.first) {
            best = {begin, end};
        }
    }
    return best;
}

}  // namespace

Result<CompactionReport> Store::compact(CompactionOptions options) {
    const std::lock_guard compaction(compaction_mutex_);
    if (options.expire_before) {
        if (auto s = flush(); !s.ok()) {
            return s.error();
        }
    }
    std::vector<SegmentPtr> inputs;
    std::uint64_t id = 0;
    {
        const std::unique_lock lock(mutex_);
        const auto [begin, end] = pick_run(segments_, options.full || options.expire_before);
        inputs.assign(segments_.begin() + static_cast<std::ptrdiff_t>(begin),
                      segments_.begin() + static_cast<std::ptrdiff_t>(end));
        id = manifest_.next_id++;
    }
    CompactionReport report;
    if (inputs.empty() || (inputs.size() < 2 && !options.expire_before)) {
        return report;
    }
    report.segments_in = inputs.size();

    // The merge runs without the lock: inputs are immutable and kept alive by shared_ptr.
    std::set<std::string> names;
    for (const auto& segment : inputs) {
        report.samples_in += segment->sample_count();
        report.bytes_in += segment->file_bytes();
        for (const auto& [name, blocks] : segment->index()) {
            names.insert(name);
        }
    }
    SegmentBuilder builder(options_.codec);
    for (const auto& name : names) {
        std::vector<std::vector<Sample>> runs;
        for (const auto& segment : inputs) {
            for (const BlockMeta& block : segment->blocks(name)) {
                auto samples = segment->read(block);
                if (!samples) {
                    return samples.error();  // inputs stay live: never compact away evidence
                }
                runs.push_back(std::move(samples).value());
            }
        }
        auto merged = merge_runs(std::move(runs));
        if (options.expire_before) {
            std::erase_if(merged, [&](const Sample& s) { return s.ts < *options.expire_before; });
        }
        builder.add_series(name, merged);
    }
    SegmentPtr output;
    if (builder.sample_count() > 0) {
        if (auto s = builder.write(segment_path(id)); !s.ok()) {
            return s.error();
        }
        auto opened = Segment::open(id, segment_path(id));
        if (!opened) {
            return opened.error();
        }
        output = std::move(opened).value();
        report.samples_out = output->sample_count();
        report.bytes_out = output->file_bytes();
    }

    const std::unique_lock lock(mutex_);
    // Flushes may have appended segments meanwhile, but only at the end.
    const auto first = std::ranges::find(segments_, inputs.front());
    const auto at = first - segments_.begin();
    auto next_segments = segments_;
    const auto erase_from = next_segments.begin() + at;
    const auto position =
        next_segments.erase(erase_from, erase_from + static_cast<std::ptrdiff_t>(inputs.size()));
    if (output) {
        next_segments.insert(position, output);
    }
    Manifest next = manifest_;
    next.segments.clear();
    for (const auto& segment : next_segments) {
        next.segments.push_back(segment->id());
    }
    if (auto s = next.save(directory_); !s.ok()) {
        return s.error();
    }
    manifest_ = std::move(next);
    segments_ = std::move(next_segments);
    for (const auto& segment : inputs) {
        std::error_code ignored;  // in-flight readers keep their mapping after unlink
        std::filesystem::remove(segment_path(segment->id()), ignored);
    }
    return report;
}

std::vector<std::string> Store::series() const {
    const std::shared_lock lock(mutex_);
    std::set<std::string> names;
    for (const auto& segment : segments_) {
        for (const auto& [name, blocks] : segment->index()) {
            names.insert(name);
        }
    }
    for (const auto& [name, samples] : memtable_.series()) {
        names.insert(name);
    }
    return {names.begin(), names.end()};
}

Result<StoreStats> Store::stats() const {
    StoreStats out;
    out.series = series().size();
    const std::shared_lock lock(mutex_);
    out.segments = segments_.size();
    out.memtable_samples = memtable_.size();
    for (const auto& segment : segments_) {
        out.segment_samples += segment->sample_count();
        out.segment_bytes += segment->file_bytes();
        for (const auto& [name, blocks] : segment->index()) {
            out.blocks += blocks.size();
            for (const BlockMeta& block : blocks) {
                const auto codec = segment->codec(block);
                if (!codec) {
                    return codec.error();
                }
                out.scaled_blocks += codec.value() == ValueCodec::ScaledDelta ? 1U : 0U;
            }
        }
    }
    return out;
}

Status Store::verify() const {
    std::vector<Sample> unused;
    for (const auto& segment : snapshot({}, 0, 0, unused)) {
        for (const auto& [name, blocks] : segment->index()) {
            for (const BlockMeta& block : blocks) {
                const auto samples = segment->read(block);
                if (!samples) {
                    return samples.error();
                }
                const auto& s = samples.value();
                const bool consistent =
                    !s.empty() && s.size() == block.count && s.front().ts == block.min_ts &&
                    s.back().ts == block.max_ts && std::ranges::is_sorted(s, {}, &Sample::ts);
                if (!consistent) {
                    return Error{ErrorCode::Corrupt, name + ": block disagrees with its index"};
                }
            }
        }
    }
    return {};
}

}  // namespace historian
