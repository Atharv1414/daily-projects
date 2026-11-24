#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace historian {

/// Appends bits most-significant-first.
class BitWriter {
  public:
    void write(std::uint64_t value, unsigned bits);
    /// Pads the last byte with zeros and returns the buffer.
    [[nodiscard]] std::vector<std::uint8_t> finish();

  private:
    std::vector<std::uint8_t> bytes_;
    std::uint8_t current_ = 0;
    unsigned used_ = 0;
};

/// Reads what BitWriter wrote. Overrunning sets a sticky failure flag instead of reading
/// out of bounds, so decoders check `ok()` once per sample rather than once per bit.
class BitReader {
  public:
    explicit BitReader(std::span<const std::uint8_t> bytes) : bytes_(bytes) {}
    [[nodiscard]] std::uint64_t read(unsigned bits);
    [[nodiscard]] bool ok() const noexcept { return !failed_; }

  private:
    std::span<const std::uint8_t> bytes_;
    std::size_t position_ = 0;  // in bits
    bool failed_ = false;
};

/// Bucketed variable-length signed integer: 0 costs one bit, small magnitudes a few.
void write_signed(BitWriter& out, std::int64_t value);
[[nodiscard]] std::int64_t read_signed(BitReader& in);

}  // namespace historian
