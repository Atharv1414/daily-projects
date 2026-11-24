#pragma once

#include <cstdint>
#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "historian/bytes.hpp"
#include "historian/codec.hpp"
#include "historian/file.hpp"
#include "historian/types.hpp"

namespace historian {

inline constexpr std::size_t kBlockSamples = 1024;

/// Index entry: where a block is, plus the statistics that let a query skip decoding it.
struct BlockMeta {
    std::uint64_t offset = 0;
    std::uint32_t length = 0;
    std::uint32_t crc = 0;
    std::uint32_t count = 0;
    TimestampMs min_ts = 0;
    TimestampMs max_ts = 0;
    double min = 0.0;
    double max = 0.0;
    double sum = 0.0;
    double first = 0.0;
    double last = 0.0;
};

/// Builds an immutable segment: magic, blocks, index, fixed-size footer. Each series may be
/// added once, and its samples must already be sorted.
class SegmentBuilder {
  public:
    explicit SegmentBuilder(CodecChoice codec = CodecChoice::Auto);
    void add_series(const std::string& series, std::span<const Sample> samples);
    [[nodiscard]] std::uint64_t sample_count() const noexcept { return samples_; }
    /// Serialises and atomically writes the file.
    [[nodiscard]] Status write(const std::filesystem::path& path) const;

  private:
    CodecChoice codec_;
    ByteWriter body_;
    std::map<std::string, std::vector<BlockMeta>> index_;
    std::uint64_t samples_ = 0;
};

/// Read side. Opening validates the footer and index checksums; each block's checksum is
/// verified when it is read.
class Segment {
  public:
    using Index = std::map<std::string, std::vector<BlockMeta>, std::less<>>;

    [[nodiscard]] static Result<std::shared_ptr<const Segment>> open(
        std::uint64_t id, const std::filesystem::path& path);

    [[nodiscard]] std::uint64_t id() const noexcept { return id_; }
    [[nodiscard]] std::uint64_t file_bytes() const noexcept { return file_.bytes().size(); }
    [[nodiscard]] std::uint64_t sample_count() const noexcept { return samples_; }
    [[nodiscard]] TimestampMs max_ts() const noexcept { return max_ts_; }
    [[nodiscard]] const Index& index() const noexcept { return index_; }
    [[nodiscard]] std::span<const BlockMeta> blocks(std::string_view series) const;
    [[nodiscard]] Result<std::vector<Sample>> read(const BlockMeta& block) const;
    [[nodiscard]] Result<ValueCodec> codec(const BlockMeta& block) const;

  private:
    [[nodiscard]] std::span<const std::uint8_t> block_bytes(const BlockMeta& block) const;
    std::uint64_t id_ = 0;
    MappedFile file_;
    Index index_;
    std::uint64_t samples_ = 0;
    TimestampMs max_ts_ = 0;
};

}  // namespace historian
