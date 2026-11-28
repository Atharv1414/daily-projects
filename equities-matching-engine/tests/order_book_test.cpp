#include <gtest/gtest.h>

#include "test_support.hpp"

namespace lob::test {
namespace {

TEST(OrderBook, RestsNonCrossingOrdersAndPublishesDepth) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Buy, 99'950, 100));
    book.submit(limit(2, Side::Buy, 99'950, 200));
    book.submit(limit(3, Side::Buy, 99'900, 300));
    book.submit(limit(4, Side::Sell, 100'050, 400));

    EXPECT_EQ(book.best_bid(), 99'950);
    EXPECT_EQ(book.best_ask(), 100'050);
    const auto d = book.depth(5);
    ASSERT_EQ(d.bids.size(), 2u);
    EXPECT_EQ(d.bids[0].qty, 300);
    EXPECT_EQ(d.bids[0].orders, 2u);
    EXPECT_EQ(d.bids[1].price, 99'900);
    ASSERT_EQ(d.asks.size(), 1u);
    EXPECT_BOOK_OK(book);
}

TEST(OrderBook, PriceTimePriorityFillsBestPriceThenOldestFirst) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Sell, 100'100, 100));
    book.submit(limit(2, Side::Sell, 100'000, 100));  // better price, later
    book.submit(limit(3, Side::Sell, 100'000, 100));  // same price, later still
    const auto& ev = book.submit(limit(4, Side::Buy, 100'100, 250));
    const auto trades = only<Trade>(ev);
    ASSERT_EQ(trades.size(), 3u);
    EXPECT_EQ(trades[0].sell_id, 2u);
    EXPECT_EQ(trades[0].price, 100'000);
    EXPECT_EQ(trades[1].sell_id, 3u);
    EXPECT_EQ(trades[2].sell_id, 1u);
    EXPECT_EQ(trades[2].price, 100'100);  // trades at the resting price, not the limit
    EXPECT_EQ(trades[2].qty, 50);
    EXPECT_EQ(trades[0].aggressor, Side::Buy);
    EXPECT_EQ(book.find(1)->visible, 50);
    EXPECT_BOOK_OK(book);
}

TEST(OrderBook, PartialFillRestsRemainderAtLimit) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Sell, 100'000, 100));
    book.submit(limit(2, Side::Buy, 100'050, 300));
    ASSERT_TRUE(book.find(2).has_value());
    EXPECT_EQ(book.find(2)->visible, 200);
    EXPECT_EQ(book.best_bid(), 100'050);
    EXPECT_FALSE(book.best_ask().has_value());
    EXPECT_BOOK_OK(book);
}

TEST(OrderBook, MarketOrderSweepsAndCancelsRemainder) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Buy, 99'950, 100));
    book.submit(limit(2, Side::Buy, 99'900, 100));
    const auto& ev = book.submit(market(3, Side::Sell, 500));
    EXPECT_EQ(traded(ev), 200);
    const auto cancels = only<Cancelled>(ev);
    ASSERT_EQ(cancels.size(), 1u);
    EXPECT_EQ(cancels[0].cancelled_qty, 300);
    EXPECT_EQ(cancels[0].reason, CancelReason::ImmediateRemainder);
    EXPECT_EQ(book.resting_orders(), 0u);
}

TEST(OrderBook, IocNeverRests) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Sell, 100'000, 100));
    NewOrder ioc = limit(2, Side::Buy, 100'000, 250);
    ioc.tif = TimeInForce::IOC;
    const auto& ev = book.submit(ioc);
    EXPECT_EQ(traded(ev), 100);
    EXPECT_FALSE(book.find(2).has_value());
    EXPECT_EQ(only<Cancelled>(ev).at(0).cancelled_qty, 150);
}

TEST(OrderBook, FillOrKillIsAllOrNothing) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Sell, 100'000, 100));
    book.submit(limit(2, Side::Sell, 100'050, 100));
    NewOrder fok = limit(3, Side::Buy, 100'050, 250);
    fok.tif = TimeInForce::FOK;
    const auto& rejected = book.submit(fok);
    ASSERT_EQ(only<Rejected>(rejected).size(), 1u);
    EXPECT_EQ(only<Rejected>(rejected)[0].reason, RejectReason::FokNotFillable);
    EXPECT_EQ(book.resting_orders(), 2u);  // nothing touched

    fok.qty = 200;
    const auto& filled = book.submit(fok);
    EXPECT_EQ(traded(filled), 200);
    EXPECT_EQ(book.resting_orders(), 0u);
}

TEST(OrderBook, FillOrKillCountsIcebergReserve) {
    OrderBook book(test_config());
    book.submit(iceberg(1, Side::Sell, 100'000, 1000, 100));
    NewOrder fok = limit(2, Side::Buy, 100'000, 900);
    fok.tif = TimeInForce::FOK;
    EXPECT_EQ(traded(book.submit(fok)), 900);
}

TEST(OrderBook, PostOnlyRejectsWhenItWouldTake) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Sell, 100'000, 100));
    NewOrder post = limit(2, Side::Buy, 100'000, 100);
    post.post_only = true;
    EXPECT_EQ(only<Rejected>(book.submit(post)).at(0).reason, RejectReason::PostOnlyWouldCross);
    post.id = 3;
    post.price = 99'950;
    EXPECT_EQ(only<Accepted>(book.submit(post)).size(), 1u);
    EXPECT_BOOK_OK(book);
}

TEST(OrderBook, IcebergShowsPeakAndLosesPriorityOnRefresh) {
    OrderBook book(test_config());
    book.submit(iceberg(1, Side::Sell, 100'000, 1000, 200));
    book.submit(limit(2, Side::Sell, 100'000, 100));
    EXPECT_EQ(book.depth(1).asks[0].qty, 300);  // only the peak is public

    // Take 250: 200 from the iceberg's peak, then the refreshed peak goes behind #2.
    const auto& ev = book.submit(limit(3, Side::Buy, 100'000, 250));
    const auto trades = only<Trade>(ev);
    ASSERT_EQ(trades.size(), 2u);
    EXPECT_EQ(trades[0].sell_id, 1u);
    EXPECT_EQ(trades[0].qty, 200);
    EXPECT_EQ(trades[1].sell_id, 2u);
    EXPECT_EQ(trades[1].qty, 50);
    const auto ice = book.find(1);
    EXPECT_EQ(ice->visible, 200);
    EXPECT_EQ(ice->hidden, 600);
    EXPECT_GT(ice->priority, book.find(2)->priority);
    EXPECT_BOOK_OK(book);
}

TEST(OrderBook, LargeOrderEatsWholeIcebergAcrossRefreshes) {
    OrderBook book(test_config());
    book.submit(iceberg(1, Side::Buy, 100'000, 1000, 300));
    const auto& ev = book.submit(limit(2, Side::Sell, 100'000, 1000));
    EXPECT_EQ(traded(ev), 1000);
    EXPECT_EQ(only<Trade>(ev).size(), 4u);  // 300 + 300 + 300 + 100
    EXPECT_EQ(book.resting_orders(), 0u);
    EXPECT_BOOK_OK(book);
}

struct StpCase {
    StpMode mode;
    bool resting_survives;
    bool incoming_cancelled;
    Qty traded;
};

class SelfTradePrevention : public ::testing::TestWithParam<StpCase> {};

TEST_P(SelfTradePrevention, AppliesTheIncomingOrdersMode) {
    const StpCase c = GetParam();
    OrderBook book(test_config());
    book.submit(limit(1, Side::Sell, 100'000, 100, /*owner=*/7));
    book.submit(limit(2, Side::Sell, 100'000, 100, /*owner=*/8));
    NewOrder buy = limit(3, Side::Buy, 100'000, 150, /*owner=*/7);
    buy.stp = c.mode;
    const auto& ev = book.submit(buy);
    EXPECT_EQ(book.find(1).has_value(), c.resting_survives);
    bool incoming_cancelled = false;
    for (const auto& x : only<Cancelled>(ev)) {
        if (x.id == 3) incoming_cancelled = x.reason == CancelReason::SelfTradePrevention;
    }
    EXPECT_EQ(incoming_cancelled, c.incoming_cancelled);
    EXPECT_EQ(traded(ev), c.traded);
    for (const auto& t : only<Trade>(ev)) EXPECT_NE(t.buyer, t.seller);
    EXPECT_BOOK_OK(book);
}

INSTANTIATE_TEST_SUITE_P(Modes, SelfTradePrevention,
                         ::testing::Values(StpCase{StpMode::CancelResting, false, false, 100},
                                           StpCase{StpMode::CancelIncoming, true, true, 0},
                                           StpCase{StpMode::CancelBoth, false, true, 0}));

TEST(OrderBook, StpNoneAllowsWashTrade) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Sell, 100'000, 100, 7));
    NewOrder buy = limit(2, Side::Buy, 100'000, 100, 7);
    buy.stp = StpMode::None;
    const auto trades = only<Trade>(book.submit(buy));
    ASSERT_EQ(trades.size(), 1u);
    EXPECT_EQ(trades[0].buyer, trades[0].seller);
}

TEST(OrderBook, CancelRemovesAndUnknownIsRejected) {
    OrderBook book(test_config());
    book.submit(iceberg(1, Side::Buy, 99'950, 900, 300));
    const auto cancelled = only<Cancelled>(book.cancel({1}));
    ASSERT_EQ(cancelled.size(), 1u);
    EXPECT_EQ(cancelled[0].cancelled_qty, 900);  // includes the hidden reserve
    EXPECT_EQ(only<Rejected>(book.cancel({1})).at(0).reason, RejectReason::UnknownOrder);
    EXPECT_EQ(book.bid_levels(), 0u);
    EXPECT_EQ(book.open_orders(1), 0u);
}

TEST(OrderBook, SizeDownAmendKeepsQueuePosition) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Buy, 99'950, 500));
    book.submit(limit(2, Side::Buy, 99'950, 500));
    const auto amended = only<Amended>(book.amend({1, 99'950, 200}));
    ASSERT_EQ(amended.size(), 1u);
    EXPECT_TRUE(amended[0].kept_priority);
    const auto trades = only<Trade>(book.submit(limit(3, Side::Sell, 99'950, 100)));
    EXPECT_EQ(trades.at(0).buy_id, 1u);
    EXPECT_EQ(book.depth(1).bids[0].qty, 600);
    EXPECT_BOOK_OK(book);
}

TEST(OrderBook, SizeUpOrRepriceLosesPriorityAndCanTrade) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Buy, 99'950, 500));
    book.submit(limit(2, Side::Buy, 99'950, 500));
    EXPECT_FALSE(only<Amended>(book.amend({1, 99'950, 600})).at(0).kept_priority);
    EXPECT_EQ(only<Trade>(book.submit(limit(3, Side::Sell, 99'950, 100))).at(0).buy_id, 2u);

    book.submit(limit(4, Side::Sell, 100'100, 300));
    const auto& ev = book.amend({2, 100'100, 400});  // re-price through the offer
    EXPECT_EQ(traded(ev), 300);
    EXPECT_EQ(book.find(2)->visible, 100);
    EXPECT_BOOK_OK(book);
}

struct RejectCase {
    const char* name;
    NewOrder order;
    RejectReason reason;
};

class Validation : public ::testing::TestWithParam<RejectCase> {};

TEST_P(Validation, RejectsBadOrders) {
    OrderBook book(test_config());
    book.submit(limit(1, Side::Buy, 99'950, 100));
    const auto rejected = only<Rejected>(book.submit(GetParam().order));
    ASSERT_EQ(rejected.size(), 1u) << GetParam().name;
    EXPECT_EQ(rejected[0].reason, GetParam().reason) << GetParam().name;
    EXPECT_EQ(book.resting_orders(), 1u);
}

INSTANTIATE_TEST_SUITE_P(
    Cases, Validation,
    ::testing::Values(
        RejectCase{"zero qty", limit(2, Side::Buy, 99'950, 0), RejectReason::InvalidQuantity},
        RejectCase{"negative qty", limit(2, Side::Buy, 99'950, -5), RejectReason::InvalidQuantity},
        RejectCase{"zero price", limit(2, Side::Buy, 0, 10), RejectReason::InvalidPrice},
        RejectCase{"off tick", limit(2, Side::Buy, 99'951, 10), RejectReason::TickSizeViolation},
        RejectCase{"duplicate", limit(1, Side::Sell, 100'500, 10), RejectReason::DuplicateOrderId},
        RejectCase{"peak above qty", iceberg(2, Side::Sell, 100'500, 100, 200),
                   RejectReason::InvalidDisplayQuantity},
        RejectCase{"peak on limit",
                   [] {
                       NewOrder o = limit(2, Side::Sell, 100'500, 100);
                       o.display_qty = 10;
                       return o;
                   }(),
                   RejectReason::InvalidDisplayQuantity}));

TEST(OrderBook, CollarBreachStartsVolatilityAuction) {
    OrderBook book(test_config(/*collar_bps=*/500, /*reference=*/100'000));
    book.submit(limit(1, Side::Buy, 99'000, 100));  // -1%: inside
    book.submit(limit(2, Side::Buy, 94'000, 100));  // -6%: outside the 5% collar
    const auto& ev = book.submit(market(3, Side::Sell, 300));
    EXPECT_EQ(traded(ev), 100);
    const auto phases = only<PhaseChanged>(ev);
    ASSERT_EQ(phases.size(), 1u);
    EXPECT_EQ(phases[0].to, Phase::Auction);
    EXPECT_EQ(phases[0].trigger_price, 94'000);
    EXPECT_EQ(book.phase(), Phase::Auction);
    EXPECT_EQ(book.find(3)->visible, 200);  // the day market order waits in the auction
    EXPECT_BOOK_OK(book);

    const auto& uncross = book.uncross();
    EXPECT_EQ(traded(uncross), 100);
    EXPECT_EQ(book.phase(), Phase::Continuous);
    // The unfilled market remainder cannot rest in continuous trading.
    const auto cancels = only<Cancelled>(uncross);
    ASSERT_EQ(cancels.size(), 1u);
    EXPECT_EQ(cancels[0].reason, CancelReason::AuctionRemainder);
    EXPECT_BOOK_OK(book);
}

TEST(OrderBook, IocInAuctionIsRejectedAndHaltBlocksEntry) {
    OrderBook book(test_config());
    book.start_auction();
    NewOrder ioc = limit(1, Side::Buy, 100'000, 100);
    ioc.tif = TimeInForce::IOC;
    EXPECT_EQ(only<Rejected>(book.submit(ioc)).at(0).reason, RejectReason::NotPermittedInPhase);
    book.halt();
    EXPECT_EQ(only<Rejected>(book.submit(limit(2, Side::Buy, 100'000, 1))).at(0).reason,
              RejectReason::MarketHalted);
    book.resume();
    EXPECT_EQ(book.phase(), Phase::Auction);  // re-opens through an auction
}

TEST(OrderBook, OpeningAuctionUncrossLeavesBookUncrossed) {
    OrderBook book(test_config(0, 100'000));
    book.start_auction();
    book.submit(limit(1, Side::Buy, 100'200, 400));
    book.submit(limit(2, Side::Buy, 100'100, 300));
    book.submit(limit(3, Side::Sell, 99'900, 250));
    book.submit(limit(4, Side::Sell, 100'100, 350));
    book.submit(limit(5, Side::Sell, 100'300, 200));
    EXPECT_FALSE(book.best_bid() < book.best_ask());  // crossed while calling

    const auto indicative = book.indicative_uncross();
    ASSERT_TRUE(indicative.has_value());
    EXPECT_EQ(indicative->price, 100'100);
    EXPECT_EQ(indicative->volume, 600);

    const auto& ev = book.uncross();
    EXPECT_EQ(traded(ev), 600);
    for (const auto& t : only<Trade>(ev)) {
        EXPECT_EQ(t.price, 100'100);
        EXPECT_TRUE(t.auction);
    }
    EXPECT_LT(*book.best_bid(), *book.best_ask());
    EXPECT_EQ(book.reference_price(), 100'100);
    EXPECT_BOOK_OK(book);
}

TEST(OrderBook, StateHashDependsOnQueueOrder) {
    OrderBook a(test_config());
    OrderBook b(test_config());
    a.submit(limit(1, Side::Buy, 99'950, 100));
    a.submit(limit(2, Side::Buy, 99'950, 100));
    b.submit(limit(2, Side::Buy, 99'950, 100));
    b.submit(limit(1, Side::Buy, 99'950, 100));
    EXPECT_NE(a.state_hash(), b.state_hash());
    EXPECT_EQ(a.depth(1).bids[0].qty, b.depth(1).bids[0].qty);
}

}  // namespace
}  // namespace lob::test
