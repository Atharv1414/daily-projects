#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "historian/types.hpp"

namespace historian {

enum class ValueCodec : std::uint8_t {
    XorFloat = 1,     ///< Gorilla-style XOR of consecutive IEEE-754 values
    ScaledDelta = 2,  ///< values are exact decimals: store deltas of value * 10^scale
};

/// Which value codecs the encoder may use. `Auto` keeps whichever is smaller per block.
enum class CodecChoice { Auto, XorOnly };

/// Losslessly compresses samples (must be sorted by timestamp). Bit-exact round trip for
/// every double, including NaN payloads and negative zero.
[[nodiscard]] std::vector<std::uint8_t> encode_block(std::span<const Sample> samples,
                                                     CodecChoice choice = CodecChoice::Auto);

[[nodiscard]] Result<std::vector<Sample>> decode_block(std::span<const std::uint8_t> bytes);

/// Value codec stored in an encoded block's header.
[[nodiscard]] Result<ValueCodec> block_codec(std::span<const std::uint8_t> bytes);

}  // namespace historian
