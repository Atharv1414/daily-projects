#include "jobsearch/segment.hpp"

#include <gtest/gtest.h>

#include <fstream>

#include "jobsearch/corpus.hpp"
#include "support.hpp"

using namespace jobsearch;
using jobsearch::testing::job;
using jobsearch::testing::TempDir;

TEST(Segment, IndexesTitleAndBodySeparately) {
    const std::vector<JobAd> jobs{job("a", "Data Engineer", "Build pipelines in Python"),
                                  job("b", "Data Analyst", "Python and SQL reporting")};
    const auto seg = Segment::build(1, jobs);
    EXPECT_EQ(seg.doc_count(), 2U);
    EXPECT_EQ(seg.doc_freq(Field::Title, "data"), 2U);
    EXPECT_EQ(seg.doc_freq(Field::Title, "python"), 0U);
    EXPECT_EQ(seg.doc_freq(Field::Body, "python"), 2U);
    EXPECT_EQ(seg.field_length(Field::Body, 0), 3U);  // "in" is a stop word
    EXPECT_EQ(seg.total_field_length(Field::Title), 4U);
    EXPECT_EQ(seg.stored(1).id, "b");
}

TEST(Segment, ExpandsPrefixesInSortedOrderWithLimit) {
    const std::vector<JobAd> jobs{job("a", "Engineer", "engine engineering engagement")};
    const auto seg = Segment::build(1, jobs);
    const auto all = seg.expand_prefix(Field::Body, "eng", 10);
    ASSERT_EQ(all.size(), 3U);
    EXPECT_EQ(all[0], "engagement");
    EXPECT_EQ(all[1], "engin");  // "engine" loses its silent e
    EXPECT_EQ(all[2], "engineer");
    EXPECT_EQ(seg.expand_prefix(Field::Body, "eng", 2).size(), 2U);
    EXPECT_TRUE(seg.expand_prefix(Field::Body, "zzz", 10).empty());
}

TEST(Segment, RejectsInvalidJobs) {
    std::vector<JobAd> jobs{job("", "Title", "body")};
    EXPECT_THROW((void)Segment::build(1, jobs), InvalidJobError);
    jobs = {job("x", "Title", "body")};
    jobs[0].salary_min = 90'000;
    EXPECT_THROW((void)Segment::build(1, jobs), InvalidJobError);
}

TEST(Segment, SerialisationRoundTripsACorpus) {
    const auto jobs = generate_corpus(CorpusOptions{2'000, 3});
    const auto seg = Segment::build(9, jobs);
    const auto bytes = seg.serialize();
    const auto back = Segment::deserialize(bytes);
    EXPECT_EQ(back.id(), 9U);
    ASSERT_EQ(back.doc_count(), seg.doc_count());
    EXPECT_EQ(back.term_count(Field::Body), seg.term_count(Field::Body));
    EXPECT_EQ(back.serialize(), bytes);  // byte-identical re-encode
    for (DocId d = 0; d < seg.doc_count(); d += 97) {
        EXPECT_EQ(back.stored(d), seg.stored(d));
    }
}

class SegmentCorruption : public ::testing::TestWithParam<std::size_t> {};

TEST_P(SegmentCorruption, FlippedByteIsDetected) {
    const auto seg = Segment::build(1, generate_corpus(CorpusOptions{200, 5}));
    auto bytes = seg.serialize();
    const auto at = GetParam() % bytes.size();
    bytes[at] = static_cast<std::uint8_t>(bytes[at] ^ 0x5AU);
    EXPECT_THROW((void)Segment::deserialize(bytes), CorruptIndexError);
}

INSTANTIATE_TEST_SUITE_P(Offsets, SegmentCorruption,
                         ::testing::Values(0U, 4U, 17U, 1'000U, 9'999U, 123'456U));

TEST(Segment, TruncatedFileIsRejected) {
    const auto seg = Segment::build(1, generate_corpus(CorpusOptions{50, 5}));
    auto bytes = seg.serialize();
    bytes.resize(bytes.size() / 2);
    EXPECT_THROW((void)Segment::deserialize(bytes), CorruptIndexError);
    EXPECT_THROW((void)Segment::deserialize(std::vector<std::uint8_t>(3, 0)), CorruptIndexError);
}

TEST(Segment, SaveAndLoadThroughAtomicWrite) {
    const TempDir dir;
    const auto seg = Segment::build(4, generate_corpus(CorpusOptions{100, 1}));
    seg.save(dir.path() / "seg.jseg");
    EXPECT_FALSE(std::filesystem::exists(dir.path() / "seg.jseg.tmp"));
    EXPECT_EQ(Segment::load(dir.path() / "seg.jseg").doc_count(), 100U);
    EXPECT_THROW((void)Segment::load(dir.path() / "missing.jseg"), SearchError);
}
