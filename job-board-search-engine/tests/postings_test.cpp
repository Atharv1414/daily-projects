#include "jobsearch/postings.hpp"

#include <gtest/gtest.h>

using namespace jobsearch;

namespace {

/// Builds postings for docs 0, step, 2*step ... with positions {doc % 5, doc % 5 + 3}.
EncodedPostings make_postings(std::uint32_t count, std::uint32_t step) {
    PostingsBuilder b;
    for (std::uint32_t i = 0; i < count; ++i) {
        const DocId doc = i * step;
        b.add(doc, doc % 5);
        b.add(doc, doc % 5 + 3);
    }
    return b.finish();
}

}  // namespace

class PostingsRoundTrip : public ::testing::TestWithParam<std::uint32_t> {};

TEST_P(PostingsRoundTrip, DecodesEveryDocAndPosition) {
    const auto count = GetParam();
    const auto p = make_postings(count, 3);
    EXPECT_EQ(p.doc_count, count);
    EXPECT_EQ(p.skips.size(), (count + kBlockSize - 1) / kBlockSize);
    std::uint32_t seen = 0;
    for (PostingIterator it(p); it.valid(); it.next()) {
        ASSERT_EQ(it.doc(), seen * 3);
        ASSERT_EQ(it.tf(), 2U);
        EXPECT_EQ(it.positions()[0], it.doc() % 5);
        EXPECT_EQ(it.positions()[1], it.doc() % 5 + 3);
        ++seen;
    }
    EXPECT_EQ(seen, count);
}

// Block boundaries are where off-by-one bugs live: 127, 128, 129 and multiples.
INSTANTIATE_TEST_SUITE_P(BlockBoundaries, PostingsRoundTrip,
                         ::testing::Values(1U, 2U, 127U, 128U, 129U, 256U, 1000U));

TEST(Postings, AdvanceUsesSkipTableAndLandsOnFirstDocAtOrAfterTarget) {
    const auto p = make_postings(10'000, 2);  // even docs 0..19998
    PostingIterator it(p);
    it.advance(15'001);
    ASSERT_TRUE(it.valid());
    EXPECT_EQ(it.doc(), 15'002U);
    EXPECT_GT(it.blocks_skipped(), 50U);  // jumped, did not decode linearly
    it.advance(15'002);                   // no-op when already there
    EXPECT_EQ(it.doc(), 15'002U);
    it.advance(30'000);
    EXPECT_FALSE(it.valid());
}

TEST(Postings, RejectsOutOfOrderInput) {
    PostingsBuilder b;
    b.add(5, 1);
    EXPECT_THROW(b.add(3, 0), SearchError);
    EXPECT_THROW(b.add(5, 1), SearchError);  // position must increase
}

TEST(Postings, EmptyListIsInvalidImmediately) {
    const EncodedPostings empty;
    const PostingIterator it(empty);
    EXPECT_FALSE(it.valid());
}

TEST(Postings, SerialisesAndRejectsInconsistentSkipTable) {
    const auto p = make_postings(300, 7);
    ByteWriter w;
    p.write(w);
    ByteReader r(w.bytes());
    EXPECT_EQ(EncodedPostings::read(r), p);

    auto bad = p;
    bad.doc_count = 1000;  // claims more blocks than the skip table has
    ByteWriter w2;
    bad.write(w2);
    ByteReader r2(w2.bytes());
    EXPECT_THROW((void)EncodedPostings::read(r2), CorruptIndexError);
}

TEST(Postings, CompressesSmallGapsToAboutTwoBytesPerPosting) {
    PostingsBuilder b;
    for (DocId d = 0; d < 50'000; ++d) {
        b.add(d, 1);
    }
    const auto p = b.finish();
    // Each posting is delta(1) + tf(1) + one position(1) = 3 bytes, vs 12 bytes raw.
    EXPECT_LE(p.bytes.size(), 50'000U * 3U);
}
