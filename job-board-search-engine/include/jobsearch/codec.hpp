#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace jobsearch {

/// Append-only little helper for building binary files.
class ByteWriter {
  public:
    void varint(std::uint64_t value);
    void u32(std::uint32_t value);  // fixed width, little endian
    void u8(std::uint8_t value) { bytes_.push_back(value); }
    void string(std::string_view s);
    void raw(std::span<const std::uint8_t> data);

    [[nodiscard]] const std::vector<std::uint8_t>& bytes() const noexcept { return bytes_; }
    [[nodiscard]] std::vector<std::uint8_t> take() noexcept { return std::move(bytes_); }
    [[nodiscard]] std::size_t size() const noexcept { return bytes_.size(); }

  private:
    std::vector<std::uint8_t> bytes_;
};

/// Bounds-checked reader. Every overrun throws CorruptIndexError instead of reading past the end.
class ByteReader {
  public:
    explicit ByteReader(std::span<const std::uint8_t> data) noexcept : data_(data) {}

    [[nodiscard]] std::uint64_t varint();
    [[nodiscard]] std::uint32_t varint32();
    [[nodiscard]] std::uint32_t u32();
    [[nodiscard]] std::uint8_t u8();
    [[nodiscard]] std::string string();
    [[nodiscard]] std::span<const std::uint8_t> raw(std::size_t n);

    [[nodiscard]] std::size_t position() const noexcept { return pos_; }
    [[nodiscard]] bool at_end() const noexcept { return pos_ == data_.size(); }
    [[nodiscard]] std::size_t remaining() const noexcept { return data_.size() - pos_; }

  private:
    std::span<const std::uint8_t> data_;
    std::size_t pos_ = 0;
};

/// Decodes one LEB128 varint starting at `pos`, advancing it. Used on the hot path by the
/// posting iterator, so it does not throw: a truncated value stops at the buffer end.
[[nodiscard]] inline std::uint64_t decode_varint(std::span<const std::uint8_t> data,
                                                 std::size_t& pos) noexcept {
    std::uint64_t value = 0;
    unsigned shift = 0;
    while (pos < data.size() && shift < 64) {
        const std::uint8_t byte = data[pos++];
        value |= static_cast<std::uint64_t>(byte & 0x7FU) << shift;
        if ((byte & 0x80U) == 0) {
            break;
        }
        shift += 7;
    }
    return value;
}

/// CRC-32 (IEEE 802.3, the zlib polynomial) for segment and manifest files.
[[nodiscard]] std::uint32_t crc32(std::span<const std::uint8_t> data) noexcept;

}  // namespace jobsearch
