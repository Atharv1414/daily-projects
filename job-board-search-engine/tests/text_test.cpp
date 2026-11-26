#include "jobsearch/text.hpp"

#include <gtest/gtest.h>

#include "jobsearch/codec.hpp"
#include "jobsearch/corpus.hpp"

using namespace jobsearch;

TEST(SplitWords, LowercasesAndKeepsLanguageSymbols) {
    const std::vector<std::string> expected{"senior", "c++", "and", "c#", "dev", "net", "core"};
    EXPECT_EQ(split_words("Senior C++ and C# dev (.NET Core)"), expected);
}

TEST(SplitWords, HandlesEmptyAndPunctuationOnly) {
    EXPECT_TRUE(split_words("").empty());
    EXPECT_TRUE(split_words(" --- !!! ").empty());
    EXPECT_TRUE(split_words("+#").empty());  // symbols only attach after a letter or digit
}

struct StemCase {
    const char* word;
    const char* stemmed;
};

class StemTest : public ::testing::TestWithParam<StemCase> {};

TEST_P(StemTest, ProducesExpectedStem) {
    EXPECT_EQ(stem(GetParam().word), GetParam().stemmed) << GetParam().word;
}

INSTANTIATE_TEST_SUITE_P(
    Stemmer, StemTest,
    ::testing::Values(StemCase{"developers", "developer"}, StemCase{"engineering", "engineer"},
                      StemCase{"running", "run"}, StemCase{"managed", "manag"},
                      StemCase{"manage", "manag"}, StemCase{"managing", "manag"},
                      StemCase{"vacancies", "vacancy"}, StemCase{"business", "business"},
                      StemCase{"analysis", "analysis"}, StemCase{"installing", "install"},
                      StemCase{"sql", "sql"}, StemCase{"c++", "c++"}, StemCase{"2026", "2026"}));

TEST(Stem, IsIdempotentOnCorpusVocabulary) {
    // Index and query both stem once; stemming an already-stemmed term must not drift
    // for the bulk of real words, or prefix queries on stems would behave oddly.
    std::size_t words = 0;
    std::size_t stable = 0;
    for (const auto& job : generate_corpus(CorpusOptions{300, 7})) {
        for (const auto& w : split_words(job.body)) {
            const auto once = stem(w);
            ++words;
            stable += (stem(once) == once) ? 1U : 0U;
        }
    }
    EXPECT_GT(static_cast<double>(stable) / static_cast<double>(words), 0.95);
}

TEST(Analyze, DropsStopWordsButKeepsPositions) {
    const auto tokens = analyze("Head of the Data team");
    ASSERT_EQ(tokens.size(), 3U);
    EXPECT_EQ(tokens[0], (Token{"head", 0}));
    EXPECT_EQ(tokens[1], (Token{"data", 3}));
    EXPECT_EQ(tokens[2], (Token{"team", 4}));
}

TEST(NormalizeTerm, StopWordsAndMultiWordInputGiveEmpty) {
    EXPECT_EQ(normalize_term("Nurses"), "nurs");  // nurse, nurses, nursing -> nurs
    EXPECT_EQ(normalize_term("the"), "");
    EXPECT_EQ(normalize_term("front-end"), "");
}

TEST(Codec, VarintRoundTripsBoundaryValues) {
    const std::vector<std::uint64_t> values{0, 1, 127, 128, 16'383, 16'384, 1ULL << 32U, ~0ULL};
    ByteWriter w;
    for (const auto v : values) {
        w.varint(v);
    }
    ByteReader r(w.bytes());
    for (const auto v : values) {
        EXPECT_EQ(r.varint(), v);
    }
    EXPECT_TRUE(r.at_end());
}

TEST(Codec, TruncatedInputThrowsInsteadOfOverreading) {
    ByteWriter w;
    w.varint(1'000'000);
    auto bytes = w.take();
    bytes.pop_back();
    ByteReader r(bytes);
    EXPECT_THROW((void)r.varint(), CorruptIndexError);
    ByteReader empty({});
    EXPECT_THROW((void)empty.u32(), CorruptIndexError);
}

TEST(Codec, Crc32MatchesKnownVector) {
    const std::string check = "123456789";
    const std::vector<std::uint8_t> bytes(check.begin(), check.end());
    EXPECT_EQ(crc32(bytes), 0xCBF43926U);
}

TEST(Corpus, IsDeterministicForASeedAndDiffersAcrossSeeds) {
    const auto a = generate_corpus(CorpusOptions{500, 11});
    const auto b = generate_corpus(CorpusOptions{500, 11});
    const auto c = generate_corpus(CorpusOptions{500, 12});
    EXPECT_EQ(a, b);
    EXPECT_NE(a, c);
    for (const auto& job : a) {
        EXPECT_LE(job.salary_min, job.salary_max) << job.id;
        EXPECT_FALSE(job.title.empty());
    }
}
