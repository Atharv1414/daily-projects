#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "lob/auction.hpp"
#include "lob/order_pool.hpp"
#include "lob/price_ladder.hpp"
#include "lob/tick_table.hpp"
#include "lob/types.hpp"

namespace lob {

struct BookConfig {
    std::string symbol = "TGX";
    TickTable ticks = TickTable::uk_liquid();
    /// Dynamic price collar in basis points around the reference price. A trade outside it
    /// stops continuous trading and starts a volatility auction. 0 disables the collar.
    std::int64_t collar_bps = 500;
    /// Reference price before the first trade (normally the previous close).
    Price reference_price = 0;
    std::size_t expected_orders = 1 << 16;
};

/// One level of published depth.
struct DepthLevel {
    Price price;
    Qty qty;
    std::uint32_t orders;
};

struct DepthSnapshot {
    std::vector<DepthLevel> bids;  ///< best first
    std::vector<DepthLevel> asks;  ///< best first
};

/// A read-only view of a resting order, for queries and tests.
struct RestingOrder {
    OrderId id;
    ParticipantId owner;
    Side side;
    Price price;
    Qty visible;
    Qty hidden;
    Seq priority;
};

/// A single-symbol central limit order book with price-time priority.
///
/// Not thread-safe: each book is owned by exactly one matching thread (see Exchange). Every
/// call appends the events it causes to an internal buffer and returns a view of them; the view
/// is valid until the next call.
class OrderBook {
  public:
    explicit OrderBook(BookConfig config);

    const std::vector<Event>& submit(const NewOrder& order);
    const std::vector<Event>& cancel(const CancelOrder& request);
    const std::vector<Event>& amend(const AmendOrder& request);
    /// Switch to the call phase of an auction (e.g. the opening auction). Resting orders stay.
    const std::vector<Event>& start_auction();
    /// Uncross the auction at the price that maximises volume, then resume continuous trading.
    const std::vector<Event>& uncross();
    const std::vector<Event>& halt();
    const std::vector<Event>& resume();

    [[nodiscard]] Phase phase() const noexcept { return phase_; }
    [[nodiscard]] const std::string& symbol() const noexcept { return config_.symbol; }
    [[nodiscard]] std::optional<Price> best_bid() const noexcept;
    [[nodiscard]] std::optional<Price> best_ask() const noexcept;
    [[nodiscard]] Price reference_price() const noexcept { return reference_; }
    [[nodiscard]] DepthSnapshot depth(std::size_t levels) const;
    [[nodiscard]] std::optional<RestingOrder> find(OrderId id) const;
    [[nodiscard]] std::size_t resting_orders() const noexcept { return index_.size(); }
    [[nodiscard]] std::uint32_t open_orders(ParticipantId owner) const;
    [[nodiscard]] std::size_t bid_levels() const noexcept { return bids_.depth(); }
    [[nodiscard]] std::size_t ask_levels() const noexcept { return asks_.depth(); }
    /// The indicative uncross while in an auction (what the venue would publish).
    [[nodiscard]] std::optional<UncrossResult> indicative_uncross() const;
    /// FNV-1a over every resting order in priority order plus phase and reference price.
    /// Two books with equal hashes hold the same orders in the same queue positions.
    [[nodiscard]] std::uint64_t state_hash() const noexcept;
    /// Checks structural invariants (links, level totals, index, no crossed book in
    /// continuous trading). Returns an empty string when everything holds.
    [[nodiscard]] std::string check_invariants() const;

  private:
    [[nodiscard]] PriceLadder& ladder(Side s) noexcept { return s == Side::Buy ? bids_ : asks_; }
    [[nodiscard]] const PriceLadder& ladder(Side s) const noexcept {
        return s == Side::Buy ? bids_ : asks_;
    }
    [[nodiscard]] bool crosses(Side side, Price limit, Price resting) const noexcept;
    [[nodiscard]] bool inside_collar(Price p) const noexcept;
    [[nodiscard]] std::optional<RejectReason> validate(const NewOrder& o) const;
    /// Quantity that could trade immediately, ignoring self-trades, capped at `wanted`.
    [[nodiscard]] Qty fillable(const NewOrder& o, Price limit, Qty wanted) const;

    void begin() {
        events_.clear();
        collar_ref_ = reference_;
    }
    /// Match `qty` of an incoming order against the opposite side. Returns the remainder.
    Qty match(const NewOrder& o, Price limit, Qty qty, bool& incoming_killed);
    void rest(const NewOrder& o, Price price, Qty qty, bool is_market);
    void remove_resting(NodeIndex idx);
    void emit_trade(const OrderNode& resting, OrderId incoming, ParticipantId incoming_owner,
                    Side aggressor, Price price, Qty qty, bool auction);
    void enter_auction(Price trigger);

    BookConfig config_;
    Phase phase_ = Phase::Continuous;
    Price reference_;
    /// Reference for the collar, fixed for the whole command so a sweep cannot creep past it
    /// one level at a time.
    Price collar_ref_ = 0;
    OrderPool pool_;
    PriceLadder bids_{Side::Buy};
    PriceLadder asks_{Side::Sell};
    std::unordered_map<OrderId, NodeIndex> index_;
    std::unordered_map<ParticipantId, std::uint32_t> open_by_owner_;
    Seq next_priority_ = 1;
    Seq next_trade_ = 1;
    std::vector<Event> events_;
};

}  // namespace lob
