#include "lob/risk.hpp"

#include <cstdint>
#include <string>

namespace lob {

const RiskLimits& PreTradeRisk::limits_for(ParticipantId who) const {
    const auto it = overrides_.find(who);
    return it == overrides_.end() ? defaults_ : it->second;
}

RiskDecision PreTradeRisk::check(const NewOrder& order, Price reference,
                                 std::uint32_t open_orders) const {
    const RiskLimits& limits = limits_for(order.owner);
    if (order.qty > limits.max_order_qty) {
        return {false, "quantity " + std::to_string(order.qty) + " above limit " +
                           std::to_string(limits.max_order_qty)};
    }
    if (open_orders >= limits.max_open_orders) {
        return {false, "open order limit " + std::to_string(limits.max_open_orders) + " reached"};
    }
    // Market orders are valued at the reference price.
    const Price valuation = order.type == OrderType::Market ? reference : order.price;
    if (valuation > 0) {
        // price units are 0.01p, so value in pounds = price * qty / 10,000. Use long double to
        // stay clear of overflow for absurd inputs (which are exactly what this check catches).
        const long double value_gbp = static_cast<long double>(valuation) *
                                      static_cast<long double>(order.qty) /
                                      (100.0L * static_cast<long double>(kPriceUnitsPerPenny));
        if (value_gbp > static_cast<long double>(limits.max_order_value_gbp)) {
            return {false, "order value above GBP " + std::to_string(limits.max_order_value_gbp)};
        }
    }
    if (order.type != OrderType::Market && reference > 0 && limits.price_band_bps > 0) {
        const Price diff =
            order.price > reference ? order.price - reference : reference - order.price;
        if (diff * 10'000 > limits.price_band_bps * reference) {
            return {false, "price " + format_price(order.price) + " outside " +
                               std::to_string(limits.price_band_bps) + "bps of reference " +
                               format_price(reference)};
        }
    }
    return {true, {}};
}

}  // namespace lob
