#include "lob/spsc_ring.hpp"

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <thread>

namespace lob {
namespace {

TEST(SpscRing, RejectsBadCapacity) {
    EXPECT_THROW(SpscRing<int>(0), std::invalid_argument);
    EXPECT_THROW(SpscRing<int>(3), std::invalid_argument);
    EXPECT_NO_THROW(SpscRing<int>(8));
}

TEST(SpscRing, FifoAndFullEmptyEdges) {
    SpscRing<int> ring(4);
    EXPECT_FALSE(ring.try_pop().has_value());
    for (int i = 0; i < 4; ++i) EXPECT_TRUE(ring.try_push(i));
    EXPECT_FALSE(ring.try_push(99));  // full
    for (int i = 0; i < 4; ++i) EXPECT_EQ(ring.try_pop().value(), i);
    EXPECT_FALSE(ring.try_pop().has_value());
    // Wrap-around many times.
    for (int i = 0; i < 1000; ++i) {
        ASSERT_TRUE(ring.try_push(i));
        ASSERT_EQ(ring.try_pop().value(), i);
    }
}

TEST(SpscRing, MoveOnlyPayloads) {
    SpscRing<std::unique_ptr<int>> ring(2);
    EXPECT_TRUE(ring.try_push(std::make_unique<int>(7)));
    auto out = ring.try_pop();
    ASSERT_TRUE(out.has_value());
    EXPECT_EQ(**out, 7);
}

TEST(SpscRing, ConcurrentProducerConsumerSeeEverythingInOrder) {
    constexpr std::uint64_t kCount = 500'000;
    SpscRing<std::uint64_t> ring(1024);
    std::uint64_t sum = 0;
    bool ordered = true;
    std::thread consumer([&] {
        std::uint64_t expected = 0;
        while (expected < kCount) {
            if (auto v = ring.try_pop()) {
                ordered = ordered && *v == expected;
                sum += *v;
                ++expected;
            }
        }
    });
    for (std::uint64_t i = 0; i < kCount;) {
        if (ring.try_push(i)) ++i;
    }
    consumer.join();
    EXPECT_TRUE(ordered);
    EXPECT_EQ(sum, kCount * (kCount - 1) / 2);
}

}  // namespace
}  // namespace lob
