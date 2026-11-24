#include "historian/segment.hpp"

#include <algorithm>
#include <limits>

namespace historian {

namespace {
constexpr std::uint32_t kMagic = 0x31475348;  // "HSG1"
constexpr std::size_t kFooterBytes = 8 + 4 + 4 + 4;

BlockMeta summarise(std::span<const Sample> samples) {
    BlockMeta meta;
    meta.count = static_cast<std::uint32_t>(samples.size());
    meta.min_ts = samples.front().ts;
    meta.max_ts = samples.back().ts;
    meta.first = samples.front().value;
    meta.last = samples.back().value;
    meta.min = meta.first;
    meta.max = meta.first;
    for (const Sample& s : samples) {
        meta.min = std::min(meta.min, s.value);
        meta.max = std::max(meta.max, s.value);
        meta.sum += s.value;
    }
    return meta;
}

Error corrupt(const std::filesystem::path& path, const char* what) {
    return {ErrorCode::Corrupt, path.filename().string() + ": " + what};
}
}  // namespace

SegmentBuilder::SegmentBuilder(CodecChoice codec) : codec_(codec) { body_.u32(kMagic); }

void SegmentBuilder::add_series(const std::string& series, std::span<const Sample> samples) {
    if (samples.empty()) {
        return;
    }
    auto& blocks = index_[series];
    while (!samples.empty()) {
        const auto chunk = samples.first(std::min(kBlockSamples, samples.size()));
        samples = samples.subspan(chunk.size());
        const auto encoded = encode_block(chunk, codec_);
        BlockMeta meta = summarise(chunk);
        meta.offset = body_.size();
        meta.length = static_cast<std::uint32_t>(encoded.size());
        meta.crc = crc32(encoded);
        body_.raw(encoded);
        blocks.push_back(meta);
        samples_ += chunk.size();
    }
}

Status SegmentBuilder::write(const std::filesystem::path& path) const {
    ByteWriter index;
    index.u32(static_cast<std::uint32_t>(index_.size()));
    for (const auto& [series, blocks] : index_) {
        index.string(series);
        index.u32(static_cast<std::uint32_t>(blocks.size()));
        for (const BlockMeta& b : blocks) {
            index.u64(b.offset);
            index.u32(b.length);
            index.u32(b.crc);
            index.u32(b.count);
            index.i64(b.min_ts);
            index.i64(b.max_ts);
            for (const double v : {b.min, b.max, b.sum, b.first, b.last}) {
                index.f64(v);
            }
        }
    }
    ByteWriter file;
    file.raw(body_.bytes());
    file.raw(index.bytes());
    file.u64(body_.size());
    file.u32(static_cast<std::uint32_t>(index.size()));
    file.u32(crc32(index.bytes()));
    file.u32(kMagic);
    return write_file_atomic(path, file.bytes());
}

Result<std::shared_ptr<const Segment>> Segment::open(std::uint64_t id,
                                                     const std::filesystem::path& path) {
    auto mapped = MappedFile::open(path);
    if (!mapped) {
        return mapped.error();
    }
    auto segment = std::make_shared<Segment>();
    segment->id_ = id;
    segment->file_ = std::move(mapped).value();
    const auto bytes = segment->file_.bytes();
    if (bytes.size() < kFooterBytes + 4) {
        return corrupt(path, "file is too short");
    }
    ByteReader footer(bytes.last(kFooterBytes));
    const std::uint64_t index_offset = footer.u64();
    const std::uint32_t index_length = footer.u32();
    const std::uint32_t index_crc = footer.u32();
    const std::uint32_t magic = footer.u32();
    const std::uint64_t body_end = bytes.size() - kFooterBytes;
    if (magic != kMagic || index_offset > body_end || index_length != body_end - index_offset) {
        return corrupt(path, "bad footer");
    }
    const auto index_bytes = bytes.subspan(index_offset, index_length);
    if (crc32(index_bytes) != index_crc) {
        return corrupt(path, "index checksum mismatch");
    }
    ByteReader in(index_bytes);
    const std::uint32_t series_count = in.u32();
    segment->max_ts_ = std::numeric_limits<TimestampMs>::min();
    for (std::uint32_t s = 0; s < series_count && in.ok(); ++s) {
        auto& blocks = segment->index_[in.string()];
        const std::uint32_t block_count = in.u32();
        for (std::uint32_t b = 0; b < block_count && in.ok(); ++b) {
            BlockMeta meta;
            meta.offset = in.u64();
            meta.length = in.u32();
            meta.crc = in.u32();
            meta.count = in.u32();
            meta.min_ts = in.i64();
            meta.max_ts = in.i64();
            meta.min = in.f64();
            meta.max = in.f64();
            meta.sum = in.f64();
            meta.first = in.f64();
            meta.last = in.f64();
            if (meta.offset > index_offset || meta.length > index_offset - meta.offset) {
                return corrupt(path, "block lies outside the file body");
            }
            segment->samples_ += meta.count;
            segment->max_ts_ = std::max(segment->max_ts_, meta.max_ts);
            blocks.push_back(meta);
        }
    }
    if (!in.ok()) {
        return corrupt(path, "index is truncated");
    }
    return std::shared_ptr<const Segment>(std::move(segment));
}

std::span<const BlockMeta> Segment::blocks(std::string_view series) const {
    const auto it = index_.find(series);
    if (it == index_.end()) {
        return {};
    }
    return it->second;
}

std::span<const std::uint8_t> Segment::block_bytes(const BlockMeta& block) const {
    return file_.bytes().subspan(block.offset, block.length);
}

Result<std::vector<Sample>> Segment::read(const BlockMeta& block) const {
    const auto bytes = block_bytes(block);
    if (crc32(bytes) != block.crc) {
        return Error{ErrorCode::Corrupt, "segment " + std::to_string(id_) +
                                             ": block checksum mismatch at offset " +
                                             std::to_string(block.offset)};
    }
    return decode_block(bytes);
}

Result<ValueCodec> Segment::codec(const BlockMeta& block) const {
    return block_codec(block_bytes(block));
}

}  // namespace historian
