#include "historian/codec.hpp"

#include <gtest/gtest.h>

#include <bit>
#include <cmath>
#include <limits>
#include <random>
#include <string>

#include "historian/bitstream.hpp"
#include "historian/bytes.hpp"

namespace historian {
namespace {

void expect_bit_exact(const std::vector<Sample>& in, CodecChoice choice) {
    const auto out = decode_block(encode_block(in, choice));
    ASSERT_TRUE(out.ok()) << out.error().message;
    ASSERT_EQ(out.value().size(), in.size());
    for (std::size_t i = 0; i < in.size(); ++i) {
        EXPECT_EQ(out.value()[i].ts, in[i].ts);
        EXPECT_EQ(std::bit_cast<std::uint64_t>(out.value()[i].value),
                  std::bit_cast<std::uint64_t>(in[i].value))
            << "sample " << i;
    }
}

ValueCodec codec_of(const std::vector<Sample>& in) { return block_codec(encode_block(in)).value(); }

TEST(Crc32, MatchesTheStandardCheckValue) {
    const std::string text = "123456789";
    const std::vector<std::uint8_t> bytes(text.begin(), text.end());
    EXPECT_EQ(crc32(bytes), 0xCBF43926U);
}

TEST(BitStream, RoundTripsMixedWidths) {
    BitWriter out;
    out.write(0b101, 3);
    out.write(0xDEADBEEFCAFEBABE, 64);
    out.write(1, 1);
    const auto bytes = out.finish();
    BitReader in(bytes);
    EXPECT_EQ(in.read(3), 0b101U);
    EXPECT_EQ(in.read(64), 0xDEADBEEFCAFEBABEU);
    EXPECT_EQ(in.read(1), 1U);
    EXPECT_TRUE(in.ok());
}

TEST(BitStream, OverrunIsStickyNotUndefined) {
    BitWriter out;
    out.write(1, 1);
    const auto bytes = out.finish();
    BitReader in(bytes);
    EXPECT_EQ(in.read(64), 0U);
    EXPECT_FALSE(in.ok());
    EXPECT_EQ(in.read(1), 0U);
    EXPECT_FALSE(in.ok());
}

class SignedCoding : public ::testing::TestWithParam<std::int64_t> {};

TEST_P(SignedCoding, RoundTrips) {
    BitWriter out;
    write_signed(out, GetParam());
    const auto bytes = out.finish();
    BitReader in(bytes);
    EXPECT_EQ(read_signed(in), GetParam());
    EXPECT_TRUE(in.ok());
}

INSTANTIATE_TEST_SUITE_P(Boundaries, SignedCoding,
                         ::testing::Values(0, 1, -1, 31, -32, 32, 1023, -1024, 1024, 524287,
                                           -524288, 524288,
                                           std::numeric_limits<std::int64_t>::max(),
                                           std::numeric_limits<std::int64_t>::min()));

class CodecRoundTrip : public ::testing::TestWithParam<CodecChoice> {};

TEST_P(CodecRoundTrip, EmptyAndSingle) {
    expect_bit_exact({}, GetParam());
    expect_bit_exact({{1'793'577'600'000, 61.5}}, GetParam());
}

TEST_P(CodecRoundTrip, SpecialDoubles) {
    using Limits = std::numeric_limits<double>;
    expect_bit_exact({{1, 0.0},
                      {2, -0.0},
                      {3, Limits::quiet_NaN()},
                      {4, Limits::infinity()},
                      {5, -Limits::infinity()},
                      {6, Limits::denorm_min()},
                      {7, Limits::max()},
                      {8, Limits::lowest()}},
                     GetParam());
}

TEST_P(CodecRoundTrip, ExtremeTimestampsDoNotOverflow) {
    using Limits = std::numeric_limits<std::int64_t>;
    expect_bit_exact({{Limits::min(), 1.0}, {0, 2.0}, {Limits::max(), 3.0}}, GetParam());
}

TEST_P(CodecRoundTrip, RandomBitPatterns) {
    std::mt19937_64 rng(7);
    for (int round = 0; round < 50; ++round) {
        std::vector<Sample> samples;
        std::int64_t ts = 0;
        for (std::size_t i = 0; i < 200; ++i) {
            ts += static_cast<std::int64_t>(rng() % 100'000);
            samples.push_back({ts, std::bit_cast<double>(rng())});
        }
        expect_bit_exact(samples, GetParam());
    }
}

TEST_P(CodecRoundTrip, RandomDecimals) {
    std::mt19937_64 rng(11);
    for (int decimals = 0; decimals <= 8; ++decimals) {
        std::vector<Sample> samples;
        for (int i = 0; i < 300; ++i) {
            const auto integer = static_cast<double>(rng() % 10'000'000);
            samples.push_back({i * 1000, integer / std::pow(10.0, decimals)});
        }
        expect_bit_exact(samples, GetParam());
    }
}

INSTANTIATE_TEST_SUITE_P(Codecs, CodecRoundTrip,
                         ::testing::Values(CodecChoice::Auto, CodecChoice::XorOnly));

TEST(CodecChoiceRules, DecimalSensorsUseScaledDeltaAndShrink) {
    std::vector<Sample> samples;
    for (int i = 0; i < 1000; ++i) {
        samples.push_back({i * 1000, (600 + i % 17) / 10.0});
    }
    EXPECT_EQ(codec_of(samples), ValueCodec::ScaledDelta);
    EXPECT_LT(encode_block(samples).size() * 2, encode_block(samples, CodecChoice::XorOnly).size());
}

TEST(CodecChoiceRules, NegativeZeroForcesXor) {
    EXPECT_EQ(codec_of({{0, 1.0}, {1, -0.0}, {2, 1.0}}), ValueCodec::XorFloat);
}

TEST(CodecChoiceRules, FullPrecisionValuesUseXor) {
    std::vector<Sample> samples;
    for (int i = 0; i < 100; ++i) {
        samples.push_back({i, std::sin(i)});
    }
    EXPECT_EQ(codec_of(samples), ValueCodec::XorFloat);
}

TEST(CodecChoiceRules, ConstantSteadySeriesCostsAboutTwoBitsPerSample) {
    std::vector<Sample> samples;
    for (int i = 0; i < 1024; ++i) {
        samples.push_back({i * 1000, 12.0});
    }
    EXPECT_LT(encode_block(samples).size(), 300U);
}

TEST(DecodeBlock, EveryTruncationIsAnErrorNotACrash) {
    std::vector<Sample> samples;
    for (int i = 0; i < 64; ++i) {
        samples.push_back({i * 1000 + i % 3, std::sin(i)});
    }
    const auto bytes = encode_block(samples);
    for (std::size_t n = 0; n < bytes.size(); ++n) {
        EXPECT_FALSE(decode_block(std::span(bytes).first(n)).ok()) << n;
    }
}

TEST(DecodeBlock, RandomGarbageNeverCrashes) {
    std::mt19937_64 rng(3);
    for (int round = 0; round < 3000; ++round) {
        std::vector<std::uint8_t> bytes(rng() % 128);
        for (auto& b : bytes) {
            b = static_cast<std::uint8_t>(rng());
        }
        if (!bytes.empty()) {
            bytes[0] = static_cast<std::uint8_t>(1 + rng() % 2);
        }
        static_cast<void>(decode_block(bytes).ok());
    }
}

TEST(DecodeBlock, ImplausibleCountIsRejectedBeforeAllocating) {
    auto bytes = encode_block(std::vector<Sample>{{1, 1.0}});
    bytes[2] = bytes[3] = bytes[4] = bytes[5] = 0xFF;
    EXPECT_FALSE(decode_block(bytes).ok());
}

}  // namespace
}  // namespace historian
