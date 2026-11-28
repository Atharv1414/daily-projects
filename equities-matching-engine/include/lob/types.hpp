#pragma once

#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <variant>

namespace lob {

/// Order identifiers are assigned by the member firm's gateway and must be unique per symbol.
using OrderId = std::uint64_t;
/// Prices are integers in hundredths of a penny (1 unit = 0.01p), so 1234.50p is 123450.
using Price = std::int64_t;
/// Quantities are whole shares.
using Qty = std::int64_t;
/// Monotonic sequence numbers stamped on resting orders (time priority) and trades.
using Seq = std::uint64_t;
/// A member firm (or one of its trading desks).
using ParticipantId = std::uint32_t;

inline constexpr Price kMarketBuyPrice = std::numeric_limits<Price>::max();
inline constexpr Price kMarketSellPrice = 0;
inline constexpr Price kPriceUnitsPerPenny = 100;

enum class Side : std::uint8_t { Buy, Sell };

[[nodiscard]] constexpr Side opposite(Side s) noexcept {
    return s == Side::Buy ? Side::Sell : Side::Buy;
}

enum class OrderType : std::uint8_t {
    Limit,    ///< rests at its price if not filled (subject to time in force)
    Market,   ///< takes whatever liquidity there is; never rests in continuous trading
    Iceberg,  ///< limit order that only shows `display_qty` at a time
};

enum class TimeInForce : std::uint8_t {
    Day,  ///< rests until filled or cancelled
    IOC,  ///< immediate or cancel: fill what you can, cancel the rest
    FOK,  ///< fill or kill: fill completely at once or not at all
};

/// Self-trade prevention: what happens when an order would trade with the same participant.
enum class StpMode : std::uint8_t {
    None,            ///< allow wash trades (some venues let a firm trade with itself)
    CancelResting,   ///< cancel the older resting order and carry on matching
    CancelIncoming,  ///< cancel the rest of the incoming order
    CancelBoth,      ///< cancel both orders
};

enum class Phase : std::uint8_t {
    Continuous,  ///< orders match as they arrive
    Auction,     ///< orders collect; nothing trades until the uncross
    Halted,      ///< nothing is accepted
};

enum class RejectReason : std::uint8_t {
    InvalidQuantity,
    InvalidPrice,
    TickSizeViolation,
    InvalidDisplayQuantity,
    DuplicateOrderId,
    UnknownOrder,
    PostOnlyWouldCross,
    FokNotFillable,
    MarketHalted,
    UnknownSymbol,
    RiskLimitBreached,
    NotPermittedInPhase,
};

enum class CancelReason : std::uint8_t {
    UserRequested,
    ImmediateRemainder,  ///< IOC or market remainder
    SelfTradePrevention,
    AuctionRemainder,  ///< market order left over after an uncross
};

struct NewOrder {
    OrderId id = 0;
    ParticipantId owner = 0;
    Side side = Side::Buy;
    OrderType type = OrderType::Limit;
    TimeInForce tif = TimeInForce::Day;
    Price price = 0;         ///< ignored for market orders
    Qty qty = 0;             ///< total quantity
    Qty display_qty = 0;     ///< iceberg peak size; 0 for other types
    bool post_only = false;  ///< reject rather than take liquidity
    StpMode stp = StpMode::CancelResting;
};

struct CancelOrder {
    OrderId id = 0;
};

/// Change price and/or remaining quantity. A pure size-down keeps time priority; anything
/// else loses it, as on most European venues.
struct AmendOrder {
    OrderId id = 0;
    Price new_price = 0;
    Qty new_qty = 0;
};

// ---- Events emitted by the book -------------------------------------------------------------

struct Accepted {
    OrderId id;
};
struct Rejected {
    OrderId id;
    RejectReason reason;
};
struct Trade {
    Seq seq;
    OrderId buy_id;
    OrderId sell_id;
    ParticipantId buyer;
    ParticipantId seller;
    Side aggressor;  ///< Buy if the buyer took liquidity; for auction trades this is Buy by
                     ///< convention
    Price price;
    Qty qty;
    bool auction;
};
struct Cancelled {
    OrderId id;
    Qty cancelled_qty;
    CancelReason reason;
};
struct Amended {
    OrderId id;
    Price price;
    Qty qty;
    bool kept_priority;
};
struct PhaseChanged {
    Phase from;
    Phase to;
    Price trigger_price;  ///< the price that broke the collar, or the uncross price
};

using Event = std::variant<Accepted, Rejected, Trade, Cancelled, Amended, PhaseChanged>;

[[nodiscard]] std::string_view to_string(Side s) noexcept;
[[nodiscard]] std::string_view to_string(OrderType t) noexcept;
[[nodiscard]] std::string_view to_string(TimeInForce t) noexcept;
[[nodiscard]] std::string_view to_string(Phase p) noexcept;
[[nodiscard]] std::string_view to_string(RejectReason r) noexcept;
[[nodiscard]] std::string_view to_string(CancelReason r) noexcept;

/// "1234.50p" for 123450.
[[nodiscard]] std::string format_price(Price p);
/// Human-readable one-line form of an event, used by the CLI and in test failure messages.
[[nodiscard]] std::string describe(const Event& e);

}  // namespace lob
