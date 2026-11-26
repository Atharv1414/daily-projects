#include "jobsearch/index.hpp"

#include <gtest/gtest.h>

#include <atomic>
#include <thread>

#include "jobsearch/corpus.hpp"
#include "jobsearch/searcher.hpp"
#include "support.hpp"

using namespace jobsearch;
using jobsearch::testing::job;
using jobsearch::testing::TempDir;

namespace {

std::uint64_t hits(const Index& index, const std::string& query) {
    SearchRequest req;
    req.query = query;
    req.facets = false;
    req.snippets = false;
    return Searcher(index.snapshot()).search(req).total_hits;
}

IndexOptions small_options() {
    IndexOptions o;
    o.flush_threshold = 10;
    o.max_segments = 3;
    o.merge_width = 2;
    return o;
}

}  // namespace

TEST(Index, WritesBecomeVisibleOnRefresh) {
    Index index;
    index.upsert(job("1", "Nurse", "ward"));
    EXPECT_EQ(hits(index, "nurse"), 0U);  // near-real-time: still buffered
    EXPECT_EQ(index.get("1")->title, "Nurse");
    index.refresh();
    EXPECT_EQ(hits(index, "nurse"), 1U);
}

TEST(Index, UpsertReplacesIndexedAndBufferedVersions) {
    Index index;
    EXPECT_FALSE(index.upsert(job("1", "Chef", "kitchen")));
    EXPECT_TRUE(index.upsert(job("1", "Head Chef", "kitchen")));  // replaced in buffer
    index.refresh();
    EXPECT_TRUE(index.upsert(job("1", "Sous Chef", "kitchen")));  // replaces indexed copy
    EXPECT_EQ(hits(index, "chef"), 0U);  // old copy deleted at once, new one buffered
    index.refresh();
    EXPECT_EQ(hits(index, "sous"), 1U);
    EXPECT_EQ(hits(index, "head"), 0U);
    EXPECT_EQ(index.stats().live_docs, 1U);
}

TEST(Index, RemoveHandlesBufferedIndexedAndUnknownIds) {
    Index index;
    index.upsert(job("1", "Electrician", "a"));
    index.upsert(job("2", "Electrician", "b"));
    index.refresh();
    index.upsert(job("3", "Electrician", "c"));
    EXPECT_TRUE(index.remove("3"));  // buffered
    EXPECT_TRUE(index.remove("1"));  // indexed: visible immediately
    EXPECT_FALSE(index.remove("1"));
    EXPECT_FALSE(index.remove("nope"));
    EXPECT_EQ(hits(index, "electrician"), 1U);
    index.refresh();
    EXPECT_EQ(hits(index, "electrician"), 1U);
}

TEST(Index, OldSnapshotsAreIsolatedFromLaterWrites) {
    Index index;
    index.upsert(job("1", "Accountant", "ACCA"));
    index.refresh();
    const auto before = index.snapshot();
    index.remove("1");
    index.upsert(job("2", "Accountant", "CIMA"));
    index.refresh();
    SearchRequest req;
    req.query = "accountant";
    const auto old = Searcher(before).search(req);
    ASSERT_EQ(old.total_hits, 1U);
    EXPECT_EQ(old.hits[0].job.id, "1");
    EXPECT_EQ(Searcher(index.snapshot()).search(req).hits[0].job.id, "2");
    EXPECT_GT(index.snapshot()->generation, before->generation);
}

TEST(Index, MergePolicyBoundsSegmentCountAndKeepsEveryDoc) {
    Index index(small_options());
    const auto corpus = generate_corpus(CorpusOptions{205, 8});
    for (const auto& j : corpus) {
        index.upsert(j);
    }
    index.refresh();
    const auto stats = index.stats();
    EXPECT_LE(stats.segments, 3U);
    EXPECT_GT(stats.merges, 0U);
    EXPECT_EQ(stats.live_docs, 205U);
    EXPECT_EQ(hits(index, ""), 205U);
    for (std::size_t i = 0; i < corpus.size(); i += 41) {
        EXPECT_EQ(index.get(corpus[i].id), corpus[i]);  // locations survive merges
    }
}

TEST(Index, HeavilyDeletedSegmentIsRewritten) {
    Index index;
    for (int i = 0; i < 10; ++i) {
        index.upsert(job(std::to_string(i), "Driver", "HGV"));
    }
    index.refresh();
    for (int i = 0; i < 4; ++i) {
        index.remove(std::to_string(i));
    }
    EXPECT_EQ(index.stats().deleted_docs, 4U);
    index.refresh();  // 40% deleted > 30% threshold
    EXPECT_EQ(index.stats().deleted_docs, 0U);
    EXPECT_EQ(hits(index, "driver"), 6U);
}

TEST(Index, ForceMergeLeavesOneCleanSegment) {
    Index index(small_options());
    for (const auto& j : generate_corpus(CorpusOptions{60, 2})) {
        index.upsert(j);
    }
    index.remove("JB100005");
    index.force_merge();
    EXPECT_EQ(index.stats().segments, 1U);
    EXPECT_EQ(index.stats().deleted_docs, 0U);
    EXPECT_EQ(index.stats().live_docs, 59U);
}

TEST(Index, SaveAndOpenPreservesDocsDeletesAndIds) {
    const TempDir dir;
    {
        Index index(small_options());
        for (const auto& j : generate_corpus(CorpusOptions{120, 4})) {
            index.upsert(j);
        }
        index.refresh();
        index.remove("JB100003");
        index.save(dir.path());
    }
    const auto opened = Index::open(dir.path(), small_options());
    EXPECT_EQ(opened->stats().live_docs, 119U);
    EXPECT_FALSE(opened->get("JB100003").has_value());
    EXPECT_TRUE(opened->get("JB100004").has_value());
    // New segments after reopening must not collide with existing file names.
    opened->upsert(job("new", "Teacher", "KS2"));
    opened->save(dir.path());
    EXPECT_EQ(Index::open(dir.path())->stats().live_docs, 120U);
}

TEST(Index, SaveRemovesSegmentFilesNoLongerInManifest) {
    const TempDir dir;
    Index index(small_options());
    for (const auto& j : generate_corpus(CorpusOptions{40, 4})) {
        index.upsert(j);
    }
    index.save(dir.path());
    index.force_merge();
    index.save(dir.path());
    std::size_t segment_files = 0;
    for (const auto& e : std::filesystem::directory_iterator(dir.path())) {
        segment_files += (e.path().extension() == ".jseg") ? 1U : 0U;
    }
    EXPECT_EQ(segment_files, 1U);
}

TEST(Index, CorruptManifestIsRejected) {
    const TempDir dir;
    Index index;
    index.upsert(job("1", "Chef", "x"));
    index.save(dir.path());
    auto bytes = read_file(dir.path() / "MANIFEST");
    bytes[6] = static_cast<std::uint8_t>(bytes[6] ^ 0xFFU);
    write_file_atomic(dir.path() / "MANIFEST", bytes);
    EXPECT_THROW((void)Index::open(dir.path()), CorruptIndexError);
}

TEST(Index, ConcurrentReadersSeeConsistentSnapshotsDuringWrites) {
    IndexOptions o;
    o.flush_threshold = 50;
    o.max_segments = 4;
    Index index(o);
    const auto corpus = generate_corpus(CorpusOptions{3'000, 21});
    std::atomic<bool> done{false};
    std::atomic<std::uint64_t> checks{0};
    std::atomic<bool> inconsistent{false};
    std::vector<std::jthread> readers;
    for (int r = 0; r < 4; ++r) {
        readers.emplace_back([&] {
            while (!done.load()) {
                const auto snap = index.snapshot();
                SearchRequest req;
                req.query = "";
                req.facets = false;
                req.snippets = false;
                // Match-all must equal the snapshot's own live count, whatever the writer does.
                if (Searcher(snap).search(req).total_hits != snap->live_docs()) {
                    inconsistent = true;
                }
                ++checks;
            }
        });
    }
    for (std::size_t i = 0; i < corpus.size(); ++i) {
        index.upsert(corpus[i]);
        if (i % 7 == 0 && i > 0) {
            index.remove(corpus[i - 1].id);
        }
    }
    index.refresh();
    done = true;
    readers.clear();
    EXPECT_FALSE(inconsistent.load());
    EXPECT_GT(checks.load(), 0U);
    EXPECT_EQ(hits(index, ""), index.stats().live_docs);
}

TEST(Index, RejectsBadOptionsAndJobs) {
    IndexOptions o;
    o.merge_width = 1;
    EXPECT_THROW(Index{o}, SearchError);
    Index index;
    EXPECT_THROW(index.upsert(job("", "x", "y")), InvalidJobError);
}
