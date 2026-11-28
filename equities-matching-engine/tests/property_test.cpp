// Randomised invariant tests: thousands of generated sessions with checks after every command.
#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

#include "lob/order_book.hpp"
#include "lob/order_flow.hpp"

namespace lob {
namespace {

/// Tracks, from events alone, how much of each order is still live. Quantity must be
/// conserved: submitted = traded + cancelled + resting, for every order.
struct Ledger {
    std::unordered_map<OrderId, Qty> submitted;
    std::unordered_map<OrderId, Qty> closed;  // traded + cancelled
    Qty buy_traded = 0;
    Qty sell_traded = 0;

    void on(const Command& c, const std::vector<Event>& events) {
        if (const auto* s = std::get_if<SubmitCmd>(&c)) {
            for (const auto& e : events) {
                if (std::holds_alternative<Accepted>(e)) submitted[s->order.id] = s->order.qty;
            }
        }
        for (const auto& e : events) {
            if (const auto* t = std::get_if<Trade>(&e)) {
                closed[t->buy_id] += t->qty;
                closed[t->sell_id] += t->qty;
                buy_traded += t->qty;
                sell_traded += t->qty;
            } else if (const auto* x = std::get_if<Cancelled>(&e)) {
                closed[x->id] += x->cancelled_qty;
            } else if (const auto* a = std::get_if<Amended>(&e)) {
                // An amend resets the order's remaining quantity: treat it as a fresh order.
                submitted[a->id] = a->qty;
                closed[a->id] = 0;
            }
        }
    }
};

const std::vector<Event>& apply(OrderBook& book, const Command& c) {
    static const std::vector<Event> kNone;
    if (const auto* s = std::get_if<SubmitCmd>(&c)) return book.submit(s->order);
    if (const auto* x = std::get_if<CancelCmd>(&c)) return book.cancel(x->request);
    if (const auto* a = std::get_if<AmendCmd>(&c)) return book.amend(a->request);
    return kNone;
}

class RandomSessions : public ::testing::TestWithParam<std::uint64_t> {};

TEST_P(RandomSessions, InvariantsHoldAfterEveryCommand) {
    FlowProfile profile;
    BookConfig cfg;
    cfg.symbol = profile.symbol;
    cfg.reference_price = profile.start_mid;
    cfg.collar_bps = 0;
    OrderBook book(cfg);
    OrderFlowGenerator gen(profile, GetParam());
    Ledger ledger;

    for (int i = 0; i < 4'000; ++i) {
        const Command c = gen.next();
        const auto& events = apply(book, c);
        gen.observe(events);
        // Amends start from what was left; record what was left before the amend.
        ledger.on(c, events);

        for (const auto& e : events) {
            if (const auto* t = std::get_if<Trade>(&e)) {
                ASSERT_GT(t->qty, 0);
                ASSERT_NE(t->buyer, t->seller) << "self-trade slipped through STP";
            }
        }
        const std::string inv = book.check_invariants();
        ASSERT_TRUE(inv.empty()) << "after command " << i << ": " << format_command(c) << "\n"
                                 << inv;
    }

    EXPECT_EQ(ledger.buy_traded, ledger.sell_traded);
    // Conservation: each order's remaining quantity on the book equals submitted - closed.
    for (const auto& [id, qty] : ledger.submitted) {
        const auto resting = book.find(id);
        const Qty remaining = resting ? resting->visible + resting->hidden : 0;
        const auto it = ledger.closed.find(id);
        const Qty closed = it == ledger.closed.end() ? 0 : it->second;
        ASSERT_EQ(qty - closed, remaining) << "order #" << id;
    }
}

INSTANTIATE_TEST_SUITE_P(Seeds, RandomSessions, ::testing::Values(1u, 2u, 3u, 42u, 2026u));

TEST(RandomSessions, AuctionUncrossNeverLeavesACrossedBook) {
    for (std::uint64_t seed = 1; seed <= 40; ++seed) {
        SplitMix64 rng(seed);
        BookConfig cfg;
        cfg.reference_price = 100'000;
        cfg.collar_bps = 0;
        OrderBook book(cfg);
        book.start_auction();
        Qty buy_interest = 0;
        for (OrderId id = 1; id <= 60; ++id) {
            NewOrder o;
            o.id = id;
            o.owner = static_cast<ParticipantId>(id);
            o.side = rng.unit() < 0.5 ? Side::Buy : Side::Sell;
            o.qty = rng.between(1, 10) * 100;
            if (rng.unit() < 0.1) {
                o.type = OrderType::Market;
            } else {
                o.price = 100'000 + rng.between(-10, 10) * 50;
            }
            if (o.side == Side::Buy) buy_interest += o.qty;
            (void)book.submit(o);
        }
        const auto indicative = book.indicative_uncross();
        const auto& events = book.uncross();
        Qty traded = 0;
        for (const auto& e : events) {
            if (const auto* t = std::get_if<Trade>(&e)) {
                traded += t->qty;
                ASSERT_EQ(t->price, indicative->price);
            }
        }
        if (indicative) {
            ASSERT_EQ(traded, indicative->volume) << "seed " << seed;
        }
        ASSERT_LE(traded, buy_interest);
        ASSERT_EQ(book.check_invariants(), "") << "seed " << seed;
    }
}

}  // namespace
}  // namespace lob
