#include "historian/store.hpp"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <limits>
#include <map>
#include <random>
#include <thread>

#include "support.hpp"

namespace historian {
namespace {

using testing_support::kAlways;
using testing_support::points;
using testing_support::StoreTest;

TEST(Memtable, SortsLateDataAndOverwritesDuplicates) {
    Memtable table;
    table.insert("a", {10, 1.0});
    table.insert("a", {30, 3.0});
    table.insert("a", {20, 2.0});
    table.insert("a", {10, 9.0});
    EXPECT_EQ(table.range("a", 0, 100), (std::vector<Sample>{{10, 9.0}, {20, 2.0}, {30, 3.0}}));
    EXPECT_EQ(table.size(), 3U);
    EXPECT_EQ(table.late_inserts(), 1U);
    EXPECT_EQ(table.overwrites(), 1U);
}

TEST(Memtable, RangeIsHalfOpen) {
    Memtable table;
    for (int i = 0; i < 5; ++i) {
        table.insert("a", {i, 0.0});
    }
    EXPECT_EQ(table.range("a", 1, 4).size(), 3U);
    EXPECT_TRUE(table.range("a", 4, 1).empty());
    EXPECT_TRUE(table.range("missing", 0, 10).empty());
}

TEST(MergeRuns, NewestRunWins) {
    const auto merged =
        merge_runs({{{1, 1.0}, {3, 1.0}}, {{2, 2.0}, {3, 2.0}}, {{3, 3.0}, {4, 3.0}}});
    EXPECT_EQ(merged, (std::vector<Sample>{{1, 1.0}, {2, 2.0}, {3, 3.0}, {4, 3.0}}));
}

TEST_F(StoreTest, ReadsItsOwnWritesBeforeAndAfterFlush) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 1000, 3000)).ok());
    EXPECT_EQ(store->scan("m/a", 0, kAlways).value().size(), 3000U);
    ASSERT_TRUE(store->flush().ok());
    const auto samples = store->scan("m/a", 1500, 1510).value();
    ASSERT_EQ(samples.size(), 10U);
    EXPECT_EQ(samples.front(), (Sample{1500, 500.0}));
    EXPECT_TRUE(store->scan("m/none", 0, kAlways).value().empty());
}

TEST_F(StoreTest, RejectsInvalidPointsAtomically) {
    auto store = open(db());
    std::vector<Point> batch = points("m/a", 0, 2);
    batch.push_back({"m/a", {5, std::numeric_limits<double>::quiet_NaN()}});
    EXPECT_EQ(store->append(batch).error().code, ErrorCode::InvalidArgument);
    batch.back() = {"", {5, 1.0}};
    EXPECT_FALSE(store->append(batch).ok());
    EXPECT_TRUE(store->scan("m/a", 0, kAlways).value().empty());
}

TEST_F(StoreTest, SecondOpenIsRefusedWhileLocked) {
    auto store = open(db());
    const auto second = Store::open(db());
    ASSERT_FALSE(second.ok());
    EXPECT_EQ(second.error().code, ErrorCode::Locked);
    store.reset();
    EXPECT_TRUE(Store::open(db()).ok());
}

TEST_F(StoreTest, LateCorrectionInNewerSegmentWins) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 0, 100)).ok());
    ASSERT_TRUE(store->flush().ok());
    ASSERT_TRUE(store->append(std::vector<Point>{{"m/a", {50, -1.0}}}).ok());
    const auto check = [&] {
        const auto all = store->scan("m/a", 0, kAlways).value();
        ASSERT_EQ(all.size(), 100U);
        EXPECT_EQ(all[50].value, -1.0);
        const auto bucket = store->aggregate("m/a", 0, 100, 100).value().front();
        EXPECT_EQ(bucket.count, 100U);
        EXPECT_EQ(bucket.min, -1.0);
    };
    check();  // correction in the memtable
    ASSERT_TRUE(store->flush().ok());
    check();  // in a newer segment
    ASSERT_TRUE(store->compact({.full = true, .expire_before = {}}).ok());
    check();  // merged
}

TEST_F(StoreTest, AggregateAnswersWholeBlocksFromTheIndex) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 0, 10 * 1024)).ok());
    ASSERT_TRUE(store->flush().ok());
    QueryStats stats;
    const auto buckets = store->aggregate("m/a", 0, 10 * 1024, 2048, &stats).value();
    EXPECT_EQ(buckets.size(), 5U);
    EXPECT_EQ(stats.blocks_from_index, 10U);
    EXPECT_EQ(stats.blocks_decoded, 0U);
    EXPECT_EQ(buckets[1].count, 2048U);
    EXPECT_DOUBLE_EQ(buckets[1].min, 2048.0);
    EXPECT_DOUBLE_EQ(buckets[1].last, 4095.0);
    EXPECT_DOUBLE_EQ(buckets[1].mean(), (2048.0 + 4095.0) / 2.0);

    ASSERT_TRUE(store->aggregate("m/a", 5, 10 * 1024, 2048, &stats).ok());
    EXPECT_EQ(stats.blocks_decoded, 1U);  // only the clipped first block
    ASSERT_TRUE(store->aggregate("m/a", 0, 1024, 2048, &stats).ok());
    EXPECT_EQ(stats.blocks_pruned, 9U);
}

TEST_F(StoreTest, OverlappingBlocksAreNeverDoubleCounted) {
    auto store = open(db());
    for (int repeat = 0; repeat < 3; ++repeat) {
        ASSERT_TRUE(store->append(points("m/a", 0, 1000, repeat)).ok());
        ASSERT_TRUE(store->flush().ok());
    }
    QueryStats stats;
    const auto buckets = store->aggregate("m/a", 0, 10'000, 10'000, &stats).value();
    ASSERT_EQ(buckets.size(), 1U);
    EXPECT_EQ(buckets[0].count, 1000U);
    EXPECT_DOUBLE_EQ(buckets[0].min, 2.0);  // last write wins
    EXPECT_EQ(stats.blocks_decoded, 3U);
    EXPECT_EQ(stats.blocks_from_index, 0U);
}

TEST_F(StoreTest, NegativeTimestampsAlignDownwards) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", -5, 10)).ok());
    const auto buckets = store->aggregate("m/a", -100, 100, 10).value();
    ASSERT_EQ(buckets.size(), 2U);
    EXPECT_EQ(buckets[0].start, -10);
    EXPECT_EQ(buckets[0].count, 5U);
}

TEST_F(StoreTest, BucketWidthMustBePositive) {
    auto store = open(db());
    EXPECT_FALSE(store->aggregate("m/a", 0, 1, 0).ok());
}

TEST_F(StoreTest, CompactionKeepsAnswersAndShrinksDuplicates) {
    auto store = open(db());
    for (int i = 0; i < 6; ++i) {
        ASSERT_TRUE(store->append(points("m/a", 0, 2000, i)).ok());
        ASSERT_TRUE(store->append(points("m/b", i * 5000, 2000)).ok());
        ASSERT_TRUE(store->flush().ok());
    }
    const auto before_a = store->scan("m/a", 0, kAlways).value();
    const auto before_b = store->scan("m/b", 0, kAlways).value();
    const auto report = store->compact();
    ASSERT_TRUE(report.ok());
    EXPECT_EQ(report.value().segments_in, 6U);
    EXPECT_EQ(report.value().samples_in, 24'000U);
    EXPECT_EQ(report.value().samples_out, 14'000U);
    EXPECT_LT(report.value().bytes_out, report.value().bytes_in);
    EXPECT_EQ(store->scan("m/a", 0, kAlways).value(), before_a);
    EXPECT_EQ(store->scan("m/b", 0, kAlways).value(), before_b);
    EXPECT_EQ(store->stats().value().segments, 1U);
    EXPECT_TRUE(store->verify().ok());
}

TEST_F(StoreTest, SizeTieredCompactionLeavesTheBigSegmentAlone) {
    auto store = open(db());
    std::vector<Point> big;
    for (int i = 0; i < 50'000; ++i) {
        big.push_back({"m/a", {i, std::sin(i)}});
    }
    ASSERT_TRUE(store->append(big).ok());
    ASSERT_TRUE(store->flush().ok());
    for (int i = 0; i < 3; ++i) {
        ASSERT_TRUE(store->append(points("m/a", 100'000 + i * 1000, 500)).ok());
        ASSERT_TRUE(store->flush().ok());
    }
    EXPECT_EQ(store->compact().value().segments_in, 3U);
    EXPECT_EQ(store->stats().value().segments, 2U);
}

TEST_F(StoreTest, RetentionDropsOldSamplesAndEmptySegments) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 0, 1000)).ok());
    ASSERT_TRUE(store->compact({.full = true, .expire_before = 400}).ok());
    EXPECT_EQ(store->scan("m/a", 0, kAlways).value().size(), 600U);
    ASSERT_TRUE(store->compact({.full = true, .expire_before = kAlways}).ok());
    EXPECT_EQ(store->stats().value().segments, 0U);
    EXPECT_TRUE(store->series().empty());
    store.reset();
    EXPECT_TRUE(open(db())->series().empty());
}

TEST_F(StoreTest, MatchesAReferenceModelUnderRandomOperations) {
    std::mt19937_64 rng(2026);
    std::map<TimestampMs, double> model;
    auto store = open(db(), 700);
    for (int step = 0; step < 400; ++step) {
        std::vector<Point> batch;
        const auto base = static_cast<TimestampMs>(rng() % 20'000);
        for (TimestampMs i = 0; i < 20; ++i) {
            const double value = static_cast<double>(rng() % 1000) / 10.0;
            const TimestampMs ts = base + i * static_cast<TimestampMs>(1 + rng() % 3);
            batch.push_back({"m/a", {ts, value}});
            model[ts] = value;
        }
        ASSERT_TRUE(store->append(batch).ok());
        if (rng() % 23 == 0) {
            ASSERT_TRUE(store->compact().ok());
        }
        if (rng() % 61 == 0) {
            store.reset();
            store = open(db(), 700);
        }
        if (step % 20 == 0) {
            const auto from = static_cast<TimestampMs>(rng() % 20'000);
            const auto to = from + static_cast<TimestampMs>(rng() % 8000);
            std::vector<Sample> expected;
            for (auto it = model.lower_bound(from); it != model.lower_bound(to); ++it) {
                expected.push_back({it->first, it->second});
            }
            ASSERT_EQ(store->scan("m/a", from, to).value(), expected);
            std::uint64_t counted = 0;
            double sum = 0.0;
            for (const auto& b : store->aggregate("m/a", from, to, 777).value()) {
                counted += b.count;
                sum += b.sum;
            }
            double expected_sum = 0.0;
            for (const auto& s : expected) {
                expected_sum += s.value;
            }
            ASSERT_EQ(counted, expected.size());
            ASSERT_NEAR(sum, expected_sum, 1e-6);
        }
    }
}

TEST_F(StoreTest, ReadersSeeConsistentBatchesDuringFlushAndCompaction) {
    auto store = open(db(), 2000);
    std::atomic<bool> done{false};
    std::atomic<int> violations{0};
    {
        std::vector<std::jthread> readers;
        for (int r = 0; r < 3; ++r) {
            readers.emplace_back([&] {
                std::size_t previous = 0;
                while (!done.load()) {
                    const auto samples = store->scan("m/a", 0, kAlways);
                    if (!samples.ok() || samples.value().size() % 100 != 0 ||
                        samples.value().size() < previous) {
                        violations.fetch_add(1);
                        break;
                    }
                    previous = samples.value().size();
                }
            });
        }
        readers.emplace_back([&] {
            while (!done.load()) {
                if (!store->compact().ok()) {
                    violations.fetch_add(1);
                    break;
                }
            }
        });
        for (int i = 0; i < 200; ++i) {
            EXPECT_TRUE(store->append(points("m/a", i * 100, 100)).ok());
        }
        done.store(true);
    }
    EXPECT_EQ(violations.load(), 0);
    EXPECT_EQ(store->scan("m/a", 0, kAlways).value().size(), 20'000U);
}

}  // namespace
}  // namespace historian
