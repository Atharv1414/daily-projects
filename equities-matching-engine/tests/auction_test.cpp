#include "lob/auction.hpp"

#include <gtest/gtest.h>

#include <vector>

namespace lob {
namespace {

TEST(Auction, MaximisesExecutableVolume) {
    const std::vector<AuctionInterest> bids{{1010, 100}, {1005, 200}, {1000, 300}};
    const std::vector<AuctionInterest> asks{{995, 150}, {1000, 150}, {1005, 300}};
    const auto r = compute_uncross(bids, asks, 1000);
    ASSERT_TRUE(r.has_value());
    // 1000: demand 600, supply 300 -> 300.  1005: demand 300, supply 600 -> 300.
    // Equal volume and equal imbalance (300), surplus on different sides -> closest to ref.
    EXPECT_EQ(r->volume, 300);
    EXPECT_EQ(r->price, 1000);
}

TEST(Auction, MinimisesImbalanceWhenVolumeTies) {
    const std::vector<AuctionInterest> bids{{1010, 500}};
    const std::vector<AuctionInterest> asks{{1000, 300}, {1005, 200}};
    // 1000: vol 300 imb 200; 1005: vol 500 imb 0 -> 1005 wins on volume anyway.
    const auto r = compute_uncross(bids, asks, 1000);
    EXPECT_EQ(r->price, 1005);
    EXPECT_EQ(r->volume, 500);
    EXPECT_EQ(r->imbalance, 0);
}

TEST(Auction, MarketPressurePushesPriceTowardsSurplus) {
    // At every tied price there is more demand than supply: choose the highest price.
    const std::vector<AuctionInterest> bids{{1020, 1000}};
    const std::vector<AuctionInterest> asks{{1000, 100}};
    // candidates 1000 and 1020 both trade 100 with a buy surplus of 900.
    EXPECT_EQ(compute_uncross(bids, asks, 1000)->price, 1020);

    const std::vector<AuctionInterest> bids2{{1020, 100}};
    const std::vector<AuctionInterest> asks2{{1000, 1000}};
    EXPECT_EQ(compute_uncross(bids2, asks2, 1020)->price, 1000);
}

TEST(Auction, ReferencePriceBreaksRemainingTies) {
    const std::vector<AuctionInterest> bids{{1020, 100}};
    const std::vector<AuctionInterest> asks{{1000, 100}};
    // Both prices trade 100 with zero imbalance.
    EXPECT_EQ(compute_uncross(bids, asks, 1018)->price, 1020);
    EXPECT_EQ(compute_uncross(bids, asks, 1001)->price, 1000);
    EXPECT_EQ(compute_uncross(bids, asks, 1010)->price, 1000);  // equidistant -> lower
}

TEST(Auction, MarketOrdersOnlyTradeAtReference) {
    const std::vector<AuctionInterest> bids{{kMarketBuyPrice, 100}};
    const std::vector<AuctionInterest> asks{{kMarketSellPrice, 60}};
    const auto r = compute_uncross(bids, asks, 1234);
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->price, 1234);
    EXPECT_EQ(r->volume, 60);
    EXPECT_FALSE(compute_uncross(bids, asks, 0).has_value());
}

TEST(Auction, NoTradeWhenBookDoesNotCross) {
    const std::vector<AuctionInterest> bids{{990, 100}};
    const std::vector<AuctionInterest> asks{{1000, 100}};
    EXPECT_FALSE(compute_uncross(bids, asks, 995).has_value());
    EXPECT_FALSE(compute_uncross({}, asks, 995).has_value());
}

TEST(Auction, RepeatedPricesAreAggregated) {
    const std::vector<AuctionInterest> bids{{1000, 50}, {1000, 50}, {1000, 100}};
    const std::vector<AuctionInterest> asks{{1000, 120}, {1000, 30}};
    const auto r = compute_uncross(bids, asks, 1000);
    EXPECT_EQ(r->volume, 150);
    EXPECT_EQ(r->imbalance, 50);
    EXPECT_EQ(r->surplus, Side::Buy);
}

}  // namespace
}  // namespace lob
