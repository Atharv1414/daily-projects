#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>

#include "lob/types.hpp"

namespace lob {

struct RiskLimits {
    Qty max_order_qty = 1'000'000;
    /// Maximum value of a single order in pounds (price * qty).
    std::int64_t max_order_value_gbp = 5'000'000;
    /// Maximum open (resting) orders per participant per symbol.
    std::uint32_t max_open_orders = 10'000;
    /// Reject limit prices further than this from the reference (fat-finger check), in bps.
    std::int64_t price_band_bps = 2'000;
};

struct RiskDecision {
    bool allowed;
    std::string reason;
};

/// Pre-trade risk checks run by the gateway before an order reaches the book. Kept separate
/// from matching so the book stays a pure, deterministic state machine and the checks can be
/// tuned per member firm without touching it.
class PreTradeRisk {
  public:
    explicit PreTradeRisk(RiskLimits defaults = {}) : defaults_(defaults) {}

    void set_limits(ParticipantId who, RiskLimits limits) { overrides_[who] = limits; }
    [[nodiscard]] const RiskLimits& limits_for(ParticipantId who) const;

    /// `reference` is the book's reference price; `open_orders` the participant's resting count.
    [[nodiscard]] RiskDecision check(const NewOrder& order, Price reference,
                                     std::uint32_t open_orders) const;

  private:
    RiskLimits defaults_;
    std::unordered_map<ParticipantId, RiskLimits> overrides_;
};

}  // namespace lob
