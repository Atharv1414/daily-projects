#include "historian/bytes.hpp"

#include <array>

namespace historian {

namespace {
constexpr std::array<std::uint32_t, 256> make_crc_table() {
    std::array<std::uint32_t, 256> table{};
    for (std::uint32_t i = 0; i < 256; ++i) {
        std::uint32_t c = i;
        for (int k = 0; k < 8; ++k) {
            c = (c & 1U) != 0 ? 0xEDB88320U ^ (c >> 1U) : c >> 1U;
        }
        table[i] = c;
    }
    return table;
}
constexpr auto kCrcTable = make_crc_table();
}  // namespace

std::uint32_t crc32(std::span<const std::uint8_t> bytes) noexcept {
    std::uint32_t crc = 0xFFFFFFFFU;
    for (const std::uint8_t b : bytes) {
        crc = kCrcTable[(crc ^ b) & 0xFFU] ^ (crc >> 8U);
    }
    return crc ^ 0xFFFFFFFFU;
}

void ByteWriter::little_endian(std::uint64_t v, unsigned n) {
    for (unsigned i = 0; i < n; ++i) {
        bytes_.push_back(static_cast<std::uint8_t>((v >> (8U * i)) & 0xFFU));
    }
}

void ByteWriter::string(std::string_view s) {
    u32(static_cast<std::uint32_t>(s.size()));
    for (const char c : s) {
        bytes_.push_back(static_cast<std::uint8_t>(c));
    }
}

void ByteWriter::raw(std::span<const std::uint8_t> data) {
    bytes_.insert(bytes_.end(), data.begin(), data.end());
}

std::span<const std::uint8_t> ByteReader::raw(std::size_t n) {
    if (failed_ || n > remaining()) {
        failed_ = true;
        return {};
    }
    const auto out = bytes_.subspan(position_, n);
    position_ += n;
    return out;
}

std::uint64_t ByteReader::little_endian(unsigned n) {
    std::uint64_t v = 0;
    unsigned shift = 0;
    for (const std::uint8_t b : raw(n)) {
        v |= static_cast<std::uint64_t>(b) << shift;
        shift += 8;
    }
    return v;
}

std::uint8_t ByteReader::u8() { return static_cast<std::uint8_t>(little_endian(1)); }
std::uint32_t ByteReader::u32() { return static_cast<std::uint32_t>(little_endian(4)); }
std::uint64_t ByteReader::u64() { return little_endian(8); }

std::string ByteReader::string() {
    const std::uint32_t n = u32();
    const auto data = raw(n);
    std::string out;
    out.reserve(data.size());
    for (const std::uint8_t b : data) {
        out.push_back(static_cast<char>(b));
    }
    return out;
}

}  // namespace historian
