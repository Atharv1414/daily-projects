#pragma once

#include <bit>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace historian {

[[nodiscard]] std::uint32_t crc32(std::span<const std::uint8_t> bytes) noexcept;

/// Little-endian serialisation, independent of host byte order.
class ByteWriter {
  public:
    void u8(std::uint8_t v) { bytes_.push_back(v); }
    void u32(std::uint32_t v) { little_endian(v, 4); }
    void u64(std::uint64_t v) { little_endian(v, 8); }
    void i64(std::int64_t v) { u64(static_cast<std::uint64_t>(v)); }
    void f64(double v) { u64(std::bit_cast<std::uint64_t>(v)); }
    void string(std::string_view s);
    void raw(std::span<const std::uint8_t> data);
    [[nodiscard]] std::size_t size() const noexcept { return bytes_.size(); }
    [[nodiscard]] const std::vector<std::uint8_t>& bytes() const noexcept { return bytes_; }

  private:
    void little_endian(std::uint64_t v, unsigned n);
    std::vector<std::uint8_t> bytes_;
};

/// Bounds-checked reader with the same sticky-failure convention as BitReader.
class ByteReader {
  public:
    explicit ByteReader(std::span<const std::uint8_t> bytes) : bytes_(bytes) {}
    [[nodiscard]] std::uint8_t u8();
    [[nodiscard]] std::uint32_t u32();
    [[nodiscard]] std::uint64_t u64();
    [[nodiscard]] std::int64_t i64() { return static_cast<std::int64_t>(u64()); }
    [[nodiscard]] double f64() { return std::bit_cast<double>(u64()); }
    [[nodiscard]] std::string string();
    [[nodiscard]] std::span<const std::uint8_t> raw(std::size_t n);
    [[nodiscard]] std::span<const std::uint8_t> rest() { return raw(remaining()); }
    [[nodiscard]] std::size_t remaining() const noexcept { return bytes_.size() - position_; }
    [[nodiscard]] bool ok() const noexcept { return !failed_; }

  private:
    [[nodiscard]] std::uint64_t little_endian(unsigned n);
    std::span<const std::uint8_t> bytes_;
    std::size_t position_ = 0;
    bool failed_ = false;
};

}  // namespace historian
