#include "lob/auction.hpp"

#include <algorithm>
#include <vector>

namespace lob {

namespace {

struct Curve {
    std::vector<Price> prices;  // ascending
    std::vector<Qty> prefix;    // prefix[i] = sum of qty for prices[0..i)
};

Curve build_curve(std::span<const AuctionInterest> side) {
    std::vector<AuctionInterest> sorted(side.begin(), side.end());
    std::sort(sorted.begin(), sorted.end(),
              [](const AuctionInterest& a, const AuctionInterest& b) { return a.price < b.price; });
    Curve c;
    c.prices.reserve(sorted.size());
    c.prefix.reserve(sorted.size() + 1);
    c.prefix.push_back(0);
    for (const auto& s : sorted) {
        c.prices.push_back(s.price);
        c.prefix.push_back(c.prefix.back() + s.qty);
    }
    return c;
}

/// Total bid quantity willing to pay at least `p`.
Qty demand_at(const Curve& bids, Price p) {
    const auto it = std::lower_bound(bids.prices.begin(), bids.prices.end(), p);
    const auto idx = static_cast<std::size_t>(it - bids.prices.begin());
    return bids.prefix.back() - bids.prefix[idx];
}

/// Total ask quantity willing to sell at `p` or less.
Qty supply_at(const Curve& asks, Price p) {
    const auto it = std::upper_bound(asks.prices.begin(), asks.prices.end(), p);
    const auto idx = static_cast<std::size_t>(it - asks.prices.begin());
    return asks.prefix[idx];
}

Price distance(Price a, Price b) { return a > b ? a - b : b - a; }

bool is_market(Price p) { return p == kMarketBuyPrice || p == kMarketSellPrice; }

}  // namespace

std::optional<UncrossResult> compute_uncross(std::span<const AuctionInterest> bids,
                                             std::span<const AuctionInterest> asks,
                                             Price reference) {
    if (bids.empty() || asks.empty()) return std::nullopt;

    std::vector<Price> candidates;
    candidates.reserve(bids.size() + asks.size());
    for (const auto& b : bids) {
        if (!is_market(b.price)) candidates.push_back(b.price);
    }
    for (const auto& a : asks) {
        if (!is_market(a.price)) candidates.push_back(a.price);
    }
    if (candidates.empty()) {
        // Only market orders on both sides: they can only trade at the reference price.
        if (reference <= 0) return std::nullopt;
        candidates.push_back(reference);
    }
    std::sort(candidates.begin(), candidates.end());
    candidates.erase(std::unique(candidates.begin(), candidates.end()), candidates.end());

    const Curve demand = build_curve(bids);
    const Curve supply = build_curve(asks);

    std::vector<UncrossResult> best;
    for (const Price p : candidates) {
        const Qty buy = demand_at(demand, p);
        const Qty sell = supply_at(supply, p);
        const Qty volume = std::min(buy, sell);
        if (volume <= 0) continue;
        UncrossResult r{p, volume, buy > sell ? buy - sell : sell - buy,
                        buy >= sell ? Side::Buy : Side::Sell};
        if (best.empty() || volume > best.front().volume ||
            (volume == best.front().volume && r.imbalance < best.front().imbalance)) {
            best.assign(1, r);
        } else if (volume == best.front().volume && r.imbalance == best.front().imbalance) {
            best.push_back(r);
        }
    }
    if (best.empty()) return std::nullopt;
    if (best.size() == 1) return best.front();

    // Rule 3: market pressure.
    const bool all_buy_surplus = std::all_of(best.begin(), best.end(), [](const auto& r) {
        return r.imbalance > 0 && r.surplus == Side::Buy;
    });
    const bool all_sell_surplus = std::all_of(best.begin(), best.end(), [](const auto& r) {
        return r.imbalance > 0 && r.surplus == Side::Sell;
    });
    if (all_buy_surplus) return best.back();    // candidates are ascending: highest price
    if (all_sell_surplus) return best.front();  // lowest price

    // Rule 4 then 5: closest to the reference, then the lower price.
    const UncrossResult* pick = &best.front();
    for (const auto& r : best) {
        const Price d = distance(r.price, reference);
        const Price dpick = distance(pick->price, reference);
        if (d < dpick) pick = &r;
    }
    return *pick;
}

}  // namespace lob
