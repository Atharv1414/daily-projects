#include "jobsearch/codec.hpp"

#include <array>
#include <limits>

#include "jobsearch/types.hpp"

namespace jobsearch {

void ByteWriter::varint(std::uint64_t value) {
    while (value >= 0x80U) {
        bytes_.push_back(static_cast<std::uint8_t>((value & 0x7FU) | 0x80U));
        value >>= 7U;
    }
    bytes_.push_back(static_cast<std::uint8_t>(value));
}

void ByteWriter::u32(std::uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) {
        bytes_.push_back(static_cast<std::uint8_t>((value >> (8U * i)) & 0xFFU));
    }
}

void ByteWriter::string(std::string_view s) {
    varint(s.size());
    for (const char c : s) {
        bytes_.push_back(static_cast<std::uint8_t>(c));
    }
}

void ByteWriter::raw(std::span<const std::uint8_t> data) {
    bytes_.insert(bytes_.end(), data.begin(), data.end());
}

std::uint64_t ByteReader::varint() {
    std::uint64_t value = 0;
    for (unsigned shift = 0; shift < 64; shift += 7) {
        if (pos_ >= data_.size()) {
            throw CorruptIndexError("truncated varint");
        }
        const std::uint8_t byte = data_[pos_++];
        value |= static_cast<std::uint64_t>(byte & 0x7FU) << shift;
        if ((byte & 0x80U) == 0) {
            return value;
        }
    }
    throw CorruptIndexError("varint longer than 64 bits");
}

std::uint32_t ByteReader::varint32() {
    const auto value = varint();
    if (value > std::numeric_limits<std::uint32_t>::max()) {
        throw CorruptIndexError("varint does not fit in 32 bits");
    }
    return static_cast<std::uint32_t>(value);
}

std::uint32_t ByteReader::u32() {
    const auto bytes = raw(4);
    std::uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) {
        value |= static_cast<std::uint32_t>(bytes[i]) << (8U * i);
    }
    return value;
}

std::uint8_t ByteReader::u8() { return raw(1)[0]; }

std::string ByteReader::string() {
    const auto n = varint();
    if (n > remaining()) {
        throw CorruptIndexError("string length past end of buffer");
    }
    const auto bytes = raw(static_cast<std::size_t>(n));
    return {bytes.begin(), bytes.end()};
}

std::span<const std::uint8_t> ByteReader::raw(std::size_t n) {
    if (n > remaining()) {
        throw CorruptIndexError("read past end of buffer");
    }
    const auto out = data_.subspan(pos_, n);
    pos_ += n;
    return out;
}

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

std::uint32_t crc32(std::span<const std::uint8_t> data) noexcept {
    std::uint32_t crc = 0xFFFFFFFFU;
    for (const std::uint8_t byte : data) {
        crc = kCrcTable[(crc ^ byte) & 0xFFU] ^ (crc >> 8U);
    }
    return crc ^ 0xFFFFFFFFU;
}

}  // namespace jobsearch
