#include "lob/exchange.hpp"

#include <gtest/gtest.h>

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <thread>
#include <variant>
#include <vector>

#include "lob/order_flow.hpp"

namespace lob {
namespace {

BookConfig cfg(const std::string& symbol, Price reference = 100'000) {
    BookConfig c;
    c.symbol = symbol;
    c.reference_price = reference;
    return c;
}

Command cmd(const char* line) { return parse_command(line).value(); }

TEST(Exchange, RoutesBySymbolAndRejectsUnknownSymbols) {
    Exchange ex;
    ex.list(cfg("TGX"));
    ex.list(cfg("BRK", 50'000));
    (void)ex.apply(cmd("NEW sym=TGX id=1 owner=1 side=B px=999.50 qty=100"));
    (void)ex.apply(
        cmd("NEW sym=BRK id=1 owner=1 side=B px=499.90 qty=100"));  // same id, other book
    EXPECT_EQ(ex.book("TGX")->resting_orders(), 1u);
    EXPECT_EQ(ex.book("BRK")->resting_orders(), 1u);
    const auto ev = ex.apply(cmd("NEW sym=XYZ id=1 owner=1 side=B px=1 qty=1"));
    ASSERT_EQ(ev.size(), 1u);
    EXPECT_EQ(std::get<Rejected>(ev[0]).reason, RejectReason::UnknownSymbol);
    EXPECT_THROW(ex.list(cfg("TGX")), std::invalid_argument);
}

TEST(Exchange, PreTradeRiskBlocksFatFingers) {
    RiskLimits limits;
    limits.max_order_qty = 10'000;
    limits.max_order_value_gbp = 50'000;
    limits.price_band_bps = 1'000;  // 10%
    limits.max_open_orders = 2;
    Exchange ex{PreTradeRisk{limits}};
    ex.list(cfg("TGX"));
    const auto reason = [&](const char* line) {
        const auto ev = ex.apply(cmd(line));
        const auto* r = std::get_if<Rejected>(&ev[0]);
        return r == nullptr ? std::string("accepted") : std::string(to_string(r->reason));
    };
    EXPECT_EQ(reason("NEW sym=TGX id=1 owner=1 side=B px=1000 qty=20000"), "pre-trade risk limit");
    EXPECT_EQ(reason("NEW sym=TGX id=2 owner=1 side=B px=1000 qty=6000"), "pre-trade risk limit");
    EXPECT_EQ(reason("NEW sym=TGX id=3 owner=1 side=B px=1200 qty=10"), "pre-trade risk limit");
    EXPECT_EQ(reason("NEW sym=TGX id=4 owner=1 side=B px=995 qty=10"), "accepted");
    EXPECT_EQ(reason("NEW sym=TGX id=5 owner=1 side=B px=995 qty=10"), "accepted");
    EXPECT_EQ(reason("NEW sym=TGX id=6 owner=1 side=B px=995 qty=10"), "pre-trade risk limit");
    EXPECT_EQ(reason("NEW sym=TGX id=7 owner=2 side=B px=995 qty=10"), "accepted");
    EXPECT_EQ(ex.market_data("TGX")->counters().rejected, 4u);
}

TEST(Exchange, MarketDataTracksOhlcAndVwap) {
    Exchange ex;
    ex.list(cfg("TGX"));
    (void)ex.apply(cmd("NEW sym=TGX id=1 owner=1 side=S px=1000 qty=100"));
    (void)ex.apply(cmd("NEW sym=TGX id=2 owner=2 side=S px=1001 qty=300"));
    (void)ex.apply(cmd("NEW sym=TGX id=3 owner=3 side=B px=1001 qty=400"));
    const TradeStats& s = ex.market_data("TGX")->stats();
    EXPECT_EQ(s.trades, 2u);
    EXPECT_EQ(s.volume, 400);
    EXPECT_EQ(*s.open, 100'000);
    EXPECT_EQ(*s.high, 100'100);
    EXPECT_DOUBLE_EQ(*s.vwap(), (100'000.0 * 100 + 100'100.0 * 300) / 400);
}

TEST(MatchingThread, ThreadedPipelineMatchesSingleThreadedResult) {
    FlowProfile profile;
    const BookConfig book = cfg(profile.symbol, profile.start_mid);
    const auto commands = generate_session(profile, 21, 30'000, book);

    Exchange direct;
    direct.list(book);
    std::size_t direct_events = 0;
    for (const auto& c : commands) direct_events += direct.apply(c).size();

    Exchange threaded;
    threaded.list(book);
    std::atomic<std::size_t> events{0};
    std::uint64_t last_seq = 0;
    bool in_order = true;
    {
        MatchingThread mt(threaded, 256, [&](const EventBatch& b) {
            in_order = in_order && b.command_seq == last_seq + 1;
            last_seq = b.command_seq;
            events.fetch_add(b.events.size());
        });
        for (const auto& c : commands) mt.submit(c);
        mt.drain_and_stop();
        EXPECT_EQ(mt.processed(), commands.size());
    }
    EXPECT_TRUE(in_order);
    EXPECT_EQ(events.load(), direct_events);
    EXPECT_EQ(threaded.state_hash(), direct.state_hash());
}

TEST(MatchingThread, TrySubmitReportsBackPressure) {
    Exchange ex;
    ex.list(cfg("TGX"));
    std::atomic<bool> release{false};
    MatchingThread mt(ex, 4, [&](const EventBatch&) {
        while (!release.load()) std::this_thread::yield();  // a stalled consumer
    });
    int accepted = 0;
    for (int i = 0; i < 50; ++i) {
        accepted += mt.try_submit(cmd("NEW sym=TGX id=1 owner=1 side=B px=1000 qty=1")) ? 1 : 0;
    }
    EXPECT_LT(accepted, 50);  // ring (4) + the one being processed, then refused
    EXPECT_LE(accepted, 6);
    release.store(true);
    mt.drain_and_stop();
}

}  // namespace
}  // namespace lob
