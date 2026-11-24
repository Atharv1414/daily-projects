#include "historian/bitstream.hpp"

#include <algorithm>
#include <array>
#include <utility>

namespace historian {

void BitWriter::write(std::uint64_t value, unsigned bits) {
    while (bits > 0) {
        const unsigned take = std::min(8U - used_, bits);
        const auto chunk = static_cast<unsigned>((value >> (bits - take)) & ((1ULL << take) - 1));
        current_ = static_cast<std::uint8_t>(current_ | (chunk << (8U - used_ - take)));
        used_ += take;
        bits -= take;
        if (used_ == 8) {
            bytes_.push_back(current_);
            current_ = 0;
            used_ = 0;
        }
    }
}

std::vector<std::uint8_t> BitWriter::finish() {
    if (used_ > 0) {
        bytes_.push_back(current_);
        current_ = 0;
        used_ = 0;
    }
    return std::exchange(bytes_, {});
}

std::uint64_t BitReader::read(unsigned bits) {
    if (failed_ || position_ + bits > bytes_.size() * 8) {
        failed_ = true;
        return 0;
    }
    std::uint64_t value = 0;
    while (bits > 0) {
        const auto offset = static_cast<unsigned>(position_ % 8);
        const unsigned take = std::min(8U - offset, bits);
        const unsigned byte = bytes_[position_ / 8];
        const unsigned chunk = (byte >> (8U - offset - take)) & ((1U << take) - 1U);
        value = (value << take) | chunk;
        position_ += take;
        bits -= take;
    }
    return value;
}

namespace {
// Prefix k ones then a zero selects a payload width; the last prefix is four ones.
constexpr std::array<unsigned, 3> kWidths{6, 11, 20};

std::uint64_t zigzag(std::int64_t v) {
    return (static_cast<std::uint64_t>(v) << 1U) ^ static_cast<std::uint64_t>(v >> 63);
}
std::int64_t unzigzag(std::uint64_t v) {
    return static_cast<std::int64_t>((v >> 1U) ^ (~(v & 1U) + 1U));
}
}  // namespace

void write_signed(BitWriter& out, std::int64_t value) {
    const std::uint64_t z = zigzag(value);
    if (z == 0) {
        out.write(0, 1);
        return;
    }
    out.write(1, 1);
    for (const unsigned width : kWidths) {
        if (z < (1ULL << width)) {
            out.write(0, 1);
            out.write(z, width);
            return;
        }
        out.write(1, 1);
    }
    out.write(z, 64);
}

std::int64_t read_signed(BitReader& in) {
    if (in.read(1) == 0) {
        return 0;
    }
    for (const unsigned width : kWidths) {
        if (in.read(1) == 0) {
            return unzigzag(in.read(width));
        }
    }
    return unzigzag(in.read(64));
}

}  // namespace historian
