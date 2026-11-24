#include "historian/codec.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <optional>

#include "historian/bitstream.hpp"
#include "historian/bytes.hpp"

namespace historian {

namespace {

constexpr std::array<double, 7> kPow10{1.0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6};
constexpr double kMaxScaled = 2251799813685248.0;  // 2^51: rounding stays exact

// Unsigned arithmetic wraps, so extreme timestamps cannot trigger signed overflow.
std::int64_t wrapping_sub(std::int64_t a, std::int64_t b) {
    return static_cast<std::int64_t>(static_cast<std::uint64_t>(a) - static_cast<std::uint64_t>(b));
}
std::int64_t wrapping_add(std::int64_t a, std::int64_t b) {
    return static_cast<std::int64_t>(static_cast<std::uint64_t>(a) + static_cast<std::uint64_t>(b));
}

std::vector<std::uint8_t> encode_timestamps(std::span<const Sample> samples) {
    BitWriter out;
    std::int64_t previous = 0;
    std::int64_t previous_delta = 0;
    for (std::size_t i = 0; i < samples.size(); ++i) {
        const std::int64_t ts = samples[i].ts;
        if (i == 0) {
            out.write(static_cast<std::uint64_t>(ts), 64);
        } else {
            const std::int64_t delta = wrapping_sub(ts, previous);
            write_signed(out, wrapping_sub(delta, previous_delta));
            previous_delta = delta;
        }
        previous = ts;
    }
    return out.finish();
}

std::vector<std::uint8_t> encode_xor(std::span<const Sample> samples) {
    BitWriter out;
    std::uint64_t previous = 0;
    unsigned lead = 64;  // 64 means "no window yet"
    unsigned trail = 0;
    for (std::size_t i = 0; i < samples.size(); ++i) {
        const auto bits = std::bit_cast<std::uint64_t>(samples[i].value);
        if (i == 0) {
            out.write(bits, 64);
            previous = bits;
            continue;
        }
        const std::uint64_t x = bits ^ previous;
        previous = bits;
        if (x == 0) {
            out.write(0, 1);
            continue;
        }
        const auto new_lead = std::min(31U, static_cast<unsigned>(std::countl_zero(x)));
        const auto new_trail = static_cast<unsigned>(std::countr_zero(x));
        if (lead != 64 && new_lead >= lead && new_trail >= trail) {
            out.write(0b10, 2);
            out.write(x >> trail, 64 - lead - trail);
        } else {
            lead = new_lead;
            trail = new_trail;
            const unsigned length = 64 - lead - trail;
            out.write(0b11, 2);
            out.write(lead, 5);
            out.write(length - 1, 6);
            out.write(x >> trail, length);
        }
    }
    return out.finish();
}

std::optional<std::int64_t> to_scaled(double value, double pow10) {
    const double scaled = std::round(value * pow10);
    if (!(std::abs(scaled) < kMaxScaled)) {  // also rejects NaN and infinities
        return std::nullopt;
    }
    const auto integer = static_cast<std::int64_t>(scaled);
    const double back = static_cast<double>(integer) / pow10;
    if (std::bit_cast<std::uint64_t>(back) != std::bit_cast<std::uint64_t>(value)) {
        return std::nullopt;
    }
    return integer;
}

/// Smallest decimal scale that represents every value bit-exactly, if there is one.
std::optional<unsigned> find_scale(std::span<const Sample> samples) {
    unsigned scale = 0;
    for (const Sample& s : samples) {
        while (scale < kPow10.size() && !to_scaled(s.value, kPow10[scale])) {
            ++scale;
        }
        if (scale == kPow10.size()) {
            return std::nullopt;
        }
    }
    // Raising the scale for a later value can overflow an earlier one, so re-check.
    const bool exact = std::ranges::all_of(
        samples, [&](const Sample& s) { return to_scaled(s.value, kPow10[scale]).has_value(); });
    return exact ? std::optional{scale} : std::nullopt;
}

std::vector<std::uint8_t> encode_scaled(std::span<const Sample> samples, unsigned scale) {
    BitWriter out;
    std::int64_t previous = 0;
    for (const Sample& s : samples) {
        const std::int64_t v = to_scaled(s.value, kPow10[scale]).value_or(0);
        write_signed(out, v - previous);
        previous = v;
    }
    return out.finish();
}

Error corrupt(const char* what) { return {ErrorCode::Corrupt, what}; }

bool decode_xor(std::span<const std::uint8_t> bytes, std::vector<Sample>& samples) {
    BitReader in(bytes);
    std::uint64_t bits = 0;
    unsigned lead = 0;
    unsigned length = 0;
    for (std::size_t i = 0; i < samples.size(); ++i) {
        if (i == 0) {
            bits = in.read(64);
        } else if (in.read(1) != 0) {
            if (in.read(1) != 0) {
                lead = static_cast<unsigned>(in.read(5));
                length = static_cast<unsigned>(in.read(6)) + 1;
            }
            if (length == 0 || lead + length > 64) {
                return false;
            }
            bits ^= in.read(length) << (64 - lead - length);
        }
        if (!in.ok()) {
            return false;
        }
        samples[i].value = std::bit_cast<double>(bits);
    }
    return true;
}

bool decode_scaled(std::span<const std::uint8_t> bytes, unsigned scale,
                   std::vector<Sample>& samples) {
    if (scale >= kPow10.size()) {
        return false;
    }
    BitReader in(bytes);
    std::int64_t v = 0;
    for (Sample& s : samples) {
        v = wrapping_add(v, read_signed(in));
        if (!in.ok()) {
            return false;
        }
        s.value = static_cast<double>(v) / kPow10[scale];
    }
    return true;
}

}  // namespace

std::vector<std::uint8_t> encode_block(std::span<const Sample> samples, CodecChoice choice) {
    const auto timestamps = encode_timestamps(samples);
    auto values = encode_xor(samples);
    auto codec = ValueCodec::XorFloat;
    unsigned scale = 0;
    if (choice == CodecChoice::Auto) {
        if (const auto found = find_scale(samples)) {
            auto scaled = encode_scaled(samples, *found);
            if (scaled.size() < values.size()) {
                values = std::move(scaled);
                codec = ValueCodec::ScaledDelta;
                scale = *found;
            }
        }
    }
    ByteWriter out;
    out.u8(static_cast<std::uint8_t>(codec));
    out.u8(static_cast<std::uint8_t>(scale));
    out.u32(static_cast<std::uint32_t>(samples.size()));
    out.u32(static_cast<std::uint32_t>(timestamps.size()));
    out.raw(timestamps);
    out.raw(values);
    return out.bytes();
}

Result<ValueCodec> block_codec(std::span<const std::uint8_t> bytes) {
    if (bytes.empty() || bytes[0] < 1 || bytes[0] > 2) {
        return corrupt("unknown value codec");
    }
    return static_cast<ValueCodec>(bytes[0]);
}

Result<std::vector<Sample>> decode_block(std::span<const std::uint8_t> bytes) {
    const auto codec = block_codec(bytes);
    if (!codec) {
        return codec.error();
    }
    ByteReader in(bytes);
    static_cast<void>(in.u8());
    const unsigned scale = in.u8();
    const std::uint32_t count = in.u32();
    const std::uint32_t ts_length = in.u32();
    const auto ts_bytes = in.raw(ts_length);
    const auto value_bytes = in.rest();
    // Every sample after the first costs at least one timestamp bit: bound the allocation.
    if (!in.ok() || count > ts_bytes.size() * 8) {
        return corrupt("block header is inconsistent");
    }
    std::vector<Sample> samples(count);
    BitReader ts_in(ts_bytes);
    std::int64_t ts = 0;
    std::int64_t delta = 0;
    for (std::size_t i = 0; i < samples.size(); ++i) {
        if (i == 0) {
            ts = static_cast<std::int64_t>(ts_in.read(64));
        } else {
            delta = wrapping_add(delta, read_signed(ts_in));
            ts = wrapping_add(ts, delta);
        }
        samples[i].ts = ts;
    }
    if (!ts_in.ok()) {
        return corrupt("timestamp stream is truncated");
    }
    const bool decoded = codec.value() == ValueCodec::XorFloat
                             ? decode_xor(value_bytes, samples)
                             : decode_scaled(value_bytes, scale, samples);
    if (!decoded) {
        return corrupt("value stream is truncated or malformed");
    }
    return samples;
}

}  // namespace historian
