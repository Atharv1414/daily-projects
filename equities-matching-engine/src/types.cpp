#include "lob/types.hpp"

#include <cstdio>
#include <string>
#include <string_view>
#include <variant>

namespace lob {

std::string_view to_string(Side s) noexcept { return s == Side::Buy ? "BUY" : "SELL"; }

std::string_view to_string(OrderType t) noexcept {
    switch (t) {
        case OrderType::Limit:
            return "LMT";
        case OrderType::Market:
            return "MKT";
        case OrderType::Iceberg:
            return "ICE";
    }
    return "?";
}

std::string_view to_string(TimeInForce t) noexcept {
    switch (t) {
        case TimeInForce::Day:
            return "DAY";
        case TimeInForce::IOC:
            return "IOC";
        case TimeInForce::FOK:
            return "FOK";
    }
    return "?";
}

std::string_view to_string(Phase p) noexcept {
    switch (p) {
        case Phase::Continuous:
            return "CONTINUOUS";
        case Phase::Auction:
            return "AUCTION";
        case Phase::Halted:
            return "HALTED";
    }
    return "?";
}

std::string_view to_string(RejectReason r) noexcept {
    switch (r) {
        case RejectReason::InvalidQuantity:
            return "invalid quantity";
        case RejectReason::InvalidPrice:
            return "invalid price";
        case RejectReason::TickSizeViolation:
            return "price not on tick";
        case RejectReason::InvalidDisplayQuantity:
            return "invalid iceberg display quantity";
        case RejectReason::DuplicateOrderId:
            return "duplicate order id";
        case RejectReason::UnknownOrder:
            return "unknown order";
        case RejectReason::PostOnlyWouldCross:
            return "post-only order would take liquidity";
        case RejectReason::FokNotFillable:
            return "fill-or-kill not fully fillable";
        case RejectReason::MarketHalted:
            return "market halted";
        case RejectReason::UnknownSymbol:
            return "unknown symbol";
        case RejectReason::RiskLimitBreached:
            return "pre-trade risk limit";
        case RejectReason::NotPermittedInPhase:
            return "not permitted in this trading phase";
    }
    return "?";
}

std::string_view to_string(CancelReason r) noexcept {
    switch (r) {
        case CancelReason::UserRequested:
            return "user";
        case CancelReason::ImmediateRemainder:
            return "unfilled remainder";
        case CancelReason::SelfTradePrevention:
            return "self-trade prevention";
        case CancelReason::AuctionRemainder:
            return "auction remainder";
    }
    return "?";
}

std::string format_price(Price p) {
    if (p == kMarketBuyPrice || p == kMarketSellPrice) return "MKT";
    const bool negative = p < 0;
    const Price a = negative ? -p : p;
    char buf[48];
    std::snprintf(buf, sizeof buf, "%s%lld.%02lldp", negative ? "-" : "",
                  static_cast<long long>(a / kPriceUnitsPerPenny),
                  static_cast<long long>(a % kPriceUnitsPerPenny));
    return buf;
}

namespace {

template <class... Fs>
struct Overloaded : Fs... {
    using Fs::operator()...;
};
template <class... Fs>
Overloaded(Fs...) -> Overloaded<Fs...>;

}  // namespace

std::string describe(const Event& e) {
    return std::visit(Overloaded{
                          [](const Accepted& a) { return "ACCEPTED #" + std::to_string(a.id); },
                          [](const Rejected& r) {
                              return "REJECTED #" + std::to_string(r.id) + " (" +
                                     std::string(to_string(r.reason)) + ")";
                          },
                          [](const Trade& t) {
                              return std::string(t.auction ? "AUCTION TRADE " : "TRADE ") + "#" +
                                     std::to_string(t.seq) + " " + std::to_string(t.qty) + " @ " +
                                     format_price(t.price) + " buy #" + std::to_string(t.buy_id) +
                                     " / sell #" + std::to_string(t.sell_id);
                          },
                          [](const Cancelled& c) {
                              return "CANCELLED #" + std::to_string(c.id) + " " +
                                     std::to_string(c.cancelled_qty) + " (" +
                                     std::string(to_string(c.reason)) + ")";
                          },
                          [](const Amended& a) {
                              return "AMENDED #" + std::to_string(a.id) + " -> " +
                                     std::to_string(a.qty) + " @ " + format_price(a.price) +
                                     (a.kept_priority ? " (kept priority)" : " (lost priority)");
                          },
                          [](const PhaseChanged& p) {
                              return "PHASE " + std::string(to_string(p.from)) + " -> " +
                                     std::string(to_string(p.to)) + " at " +
                                     format_price(p.trigger_price);
                          },
                      },
                      e);
}

}  // namespace lob
