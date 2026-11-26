#include "jobsearch/index.hpp"

#include <algorithm>
#include <numeric>
#include <set>

#include "jobsearch/codec.hpp"

namespace jobsearch {
namespace {

constexpr std::uint32_t kManifestMagic = 0x4E414D4AU;  // "JMAN"
constexpr std::uint8_t kManifestVersion = 1;
constexpr std::string_view kManifestName = "MANIFEST";

std::string segment_file_name(std::uint64_t id) { return "seg_" + std::to_string(id) + ".jseg"; }

SegmentView make_view(std::shared_ptr<const Segment> segment) {
    auto deleted = std::make_shared<const DeleteSet>(segment->doc_count(), false);
    return SegmentView{std::move(segment), std::move(deleted), 0};
}

}  // namespace

std::uint64_t Snapshot::live_docs() const {
    return std::accumulate(
        segments.begin(), segments.end(), std::uint64_t{0},
        [](std::uint64_t acc, const SegmentView& v) { return acc + v.live_docs(); });
}

std::uint64_t Snapshot::total_docs() const {
    return std::accumulate(
        segments.begin(), segments.end(), std::uint64_t{0},
        [](std::uint64_t acc, const SegmentView& v) { return acc + v.segment->doc_count(); });
}

Index::Index(IndexOptions options)
    : options_(options), current_(std::make_shared<const Snapshot>()) {
    if (options_.flush_threshold == 0 || options_.merge_width < 2 || options_.max_segments == 0) {
        throw SearchError("invalid index options");
    }
}

std::shared_ptr<const Snapshot> Index::snapshot() const {
    const std::lock_guard lock(snapshot_mu_);
    return current_;
}

void Index::publish_locked(std::vector<SegmentView> segments) {
    auto next = std::make_shared<Snapshot>();
    next->segments = std::move(segments);
    {
        const std::lock_guard lock(snapshot_mu_);
        next->generation = current_->generation + 1;
        current_ = std::move(next);
    }
}

bool Index::upsert(JobAd job) {
    validate_job(job);
    const std::lock_guard lock(write_mu_);
    if (const auto it = buffered_.find(job.id); it != buffered_.end()) {
        buffer_[it->second] = std::move(job);
        return true;
    }
    const bool replaced = delete_indexed_locked(job.id);
    buffered_.emplace(job.id, buffer_.size());
    buffer_.push_back(std::move(job));
    if (buffer_.size() >= options_.flush_threshold) {
        flush_locked();
        maybe_merge_locked();
    }
    return replaced;
}

bool Index::remove(std::string_view job_id) {
    const std::lock_guard lock(write_mu_);
    const std::string key(job_id);
    if (const auto it = buffered_.find(key); it != buffered_.end()) {
        const std::size_t slot = it->second;
        buffered_.erase(it);
        if (slot + 1 != buffer_.size()) {
            buffer_[slot] = std::move(buffer_.back());
            buffered_[buffer_[slot].id] = slot;
        }
        buffer_.pop_back();
        return true;
    }
    return delete_indexed_locked(job_id);
}

bool Index::delete_indexed_locked(std::string_view job_id) {
    const auto it = locations_.find(std::string(job_id));
    if (it == locations_.end()) {
        return false;
    }
    const Location loc = it->second;
    locations_.erase(it);
    auto segments = snapshot()->segments;
    for (auto& view : segments) {
        if (view.segment->id() == loc.segment_id) {
            auto copy = std::make_shared<DeleteSet>(*view.deleted);  // copy-on-write
            (*copy)[loc.doc] = true;
            view.deleted = std::move(copy);
            ++view.deleted_count;
            break;
        }
    }
    publish_locked(std::move(segments));
    return true;
}

void Index::refresh() {
    const std::lock_guard lock(write_mu_);
    flush_locked();
    maybe_merge_locked();
}

void Index::force_merge() {
    const std::lock_guard lock(write_mu_);
    flush_locked();
    const auto count = snapshot()->segments.size();
    if (count > 1 || (count == 1 && snapshot()->segments[0].deleted_count > 0)) {
        std::vector<std::size_t> all(count);
        std::iota(all.begin(), all.end(), std::size_t{0});
        merge_locked(std::move(all));
    }
}

void Index::reindex_locations_locked(const SegmentView& view) {
    const auto& seg = *view.segment;
    for (DocId d = 0; d < seg.doc_count(); ++d) {
        if (view.is_live(d)) {
            locations_[seg.stored(d).id] = Location{seg.id(), d};
        }
    }
}

void Index::flush_locked() {
    if (buffer_.empty()) {
        return;
    }
    auto segment = std::make_shared<const Segment>(Segment::build(next_segment_id_++, buffer_));
    auto view = make_view(std::move(segment));
    reindex_locations_locked(view);
    auto segments = snapshot()->segments;
    segments.push_back(std::move(view));
    buffer_.clear();
    buffered_.clear();
    ++flushes_;
    publish_locked(std::move(segments));
}

void Index::merge_locked(std::vector<std::size_t> victims) {
    const auto snap = snapshot();
    std::sort(victims.begin(), victims.end());
    std::vector<JobAd> live;
    for (const auto i : victims) {
        const auto& view = snap->segments[i];
        for (DocId d = 0; d < view.segment->doc_count(); ++d) {
            if (view.is_live(d)) {
                live.push_back(view.segment->stored(d));
            }
        }
    }
    std::vector<SegmentView> segments;
    for (std::size_t i = 0; i < snap->segments.size(); ++i) {
        if (!std::binary_search(victims.begin(), victims.end(), i)) {
            segments.push_back(snap->segments[i]);
        }
    }
    if (!live.empty()) {
        auto merged =
            make_view(std::make_shared<const Segment>(Segment::build(next_segment_id_++, live)));
        reindex_locations_locked(merged);
        segments.push_back(std::move(merged));
    }
    ++merges_;
    publish_locked(std::move(segments));
}

void Index::maybe_merge_locked() {
    // 1. Rewrite segments that are mostly tombstones; they waste space and skew BM25 stats.
    for (bool again = true; again;) {
        again = false;
        const auto snap = snapshot();
        for (std::size_t i = 0; i < snap->segments.size(); ++i) {
            const auto& v = snap->segments[i];
            const double ratio =
                static_cast<double>(v.deleted_count) /
                static_cast<double>(std::max<std::uint32_t>(1, v.segment->doc_count()));
            if (ratio > options_.max_deleted_ratio) {
                merge_locked({i});
                again = true;
                break;
            }
        }
    }
    // 2. Size-tiered: while there are too many segments, merge the smallest few together.
    while (snapshot()->segments.size() > options_.max_segments) {
        const auto snap = snapshot();
        std::vector<std::size_t> order(snap->segments.size());
        std::iota(order.begin(), order.end(), std::size_t{0});
        std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
            return snap->segments[a].live_docs() < snap->segments[b].live_docs();
        });
        order.resize(std::min(options_.merge_width, order.size()));
        merge_locked(std::move(order));
    }
}

IndexStats Index::stats() const {
    const std::lock_guard lock(write_mu_);
    const auto snap = snapshot();
    IndexStats s;
    s.generation = snap->generation;
    s.segments = snap->segments.size();
    s.live_docs = snap->live_docs();
    s.deleted_docs = snap->total_docs() - s.live_docs;
    s.buffered_docs = buffer_.size();
    for (const auto& v : snap->segments) {
        s.postings_bytes += v.segment->postings_bytes();
    }
    s.flushes = flushes_;
    s.merges = merges_;
    return s;
}

std::optional<JobAd> Index::get(std::string_view job_id) const {
    const std::lock_guard lock(write_mu_);
    const std::string key(job_id);
    if (const auto it = buffered_.find(key); it != buffered_.end()) {
        return buffer_[it->second];
    }
    const auto it = locations_.find(key);
    if (it == locations_.end()) {
        return std::nullopt;
    }
    for (const auto& v : snapshot()->segments) {
        if (v.segment->id() == it->second.segment_id) {
            return v.segment->stored(it->second.doc);
        }
    }
    return std::nullopt;
}

void Index::save(const std::filesystem::path& dir) {
    const std::lock_guard lock(write_mu_);
    flush_locked();
    std::filesystem::create_directories(dir);
    const auto snap = snapshot();
    ByteWriter w;
    w.u32(kManifestMagic);
    w.u8(kManifestVersion);
    w.varint(snap->generation);
    w.varint(next_segment_id_);
    w.varint(snap->segments.size());
    std::set<std::string> keep{std::string(kManifestName)};
    for (const auto& v : snap->segments) {
        const auto name = segment_file_name(v.segment->id());
        keep.insert(name);
        if (!std::filesystem::exists(dir / name)) {  // segments are immutable: write once
            v.segment->save(dir / name);
        }
        w.varint(v.segment->id());
        w.varint(v.deleted_count);
        for (DocId d = 0; d < v.segment->doc_count(); ++d) {
            if (!v.is_live(d)) {
                w.varint(d);
            }
        }
    }
    w.u32(crc32(w.bytes()));
    write_file_atomic(dir / kManifestName, w.bytes());
    // Only after the new manifest is durable is it safe to remove files it no longer names.
    for (const auto& entry : std::filesystem::directory_iterator(dir)) {
        const auto name = entry.path().filename().string();
        if (name.starts_with("seg_") && !keep.contains(name)) {
            std::filesystem::remove(entry.path());
        }
    }
}

std::unique_ptr<Index> Index::open(const std::filesystem::path& dir, IndexOptions options) {
    const auto bytes = read_file(dir / kManifestName);
    if (bytes.size() < 9) {
        throw CorruptIndexError("manifest too small");
    }
    const std::span<const std::uint8_t> all(bytes);
    ByteReader tail(all.last(4));
    if (crc32(all.first(all.size() - 4)) != tail.u32()) {
        throw CorruptIndexError("manifest checksum mismatch");
    }
    ByteReader r(all.first(all.size() - 4));
    if (r.u32() != kManifestMagic || r.u8() != kManifestVersion) {
        throw CorruptIndexError("not a manifest file");
    }
    auto index = std::make_unique<Index>(options);
    const auto generation = r.varint();
    index->next_segment_id_ = r.varint();
    const auto count = r.varint();
    std::vector<SegmentView> segments;
    for (std::uint64_t i = 0; i < count; ++i) {
        const auto id = r.varint();
        auto segment = std::make_shared<const Segment>(Segment::load(dir / segment_file_name(id)));
        if (segment->id() != id) {
            throw CorruptIndexError("segment file id does not match manifest");
        }
        auto deleted = std::make_shared<DeleteSet>(segment->doc_count(), false);
        const auto deleted_count = r.varint32();
        for (std::uint32_t k = 0; k < deleted_count; ++k) {
            const auto doc = r.varint32();
            if (doc >= segment->doc_count()) {
                throw CorruptIndexError("deleted doc id out of range");
            }
            (*deleted)[doc] = true;
        }
        SegmentView view{std::move(segment), std::move(deleted), deleted_count};
        index->reindex_locations_locked(view);
        segments.push_back(std::move(view));
    }
    auto snap = std::make_shared<Snapshot>();
    snap->generation = generation;
    snap->segments = std::move(segments);
    index->current_ = std::move(snap);
    return index;
}

}  // namespace jobsearch
