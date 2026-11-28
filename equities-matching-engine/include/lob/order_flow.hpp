#pragma once

#include <cstdint>
#include <span>
#include <string>
#include <unordered_map>
#include <vector>

#include "lob/command.hpp"
#include "lob/order_book.hpp"
#include "lob/tick_table.hpp"

namespace lob {

/// SplitMix64: tiny, fast and, unlike std::uniform_*_distribution, gives the same numbers on
/// libstdc++ and libc++, so generated sessions are identical on every CI compiler.
class SplitMix64 {
  public:
    explicit SplitMix64(std::uint64_t seed) : state_(seed) {}
    [[nodiscard]] std::uint64_t next() noexcept {
        std::uint64_t z = (state_ += 0x9E37'79B9'7F4A'7C15ull);
        z = (z ^ (z >> 30)) * 0xBF58'476D'1CE4'E5B9ull;
        z = (z ^ (z >> 27)) * 0x94D0'49BB'1331'11EBull;
        return z ^ (z >> 31);
    }
    /// Uniform integer in [lo, hi].
    [[nodiscard]] std::int64_t between(std::int64_t lo, std::int64_t hi) noexcept;
    /// Uniform double in [0, 1).
    [[nodiscard]] double unit() noexcept;

  private:
    std::uint64_t state_;
};

struct FlowProfile {
    std::string symbol = "TGX";
    Price start_mid = 123450;  ///< 1234.50p
    std::uint32_t participants = 40;
    /// Percentages of each command kind; the remainder are plain day limit orders.
    int pct_cancel = 30;
    int pct_amend = 6;
    int pct_marketable = 8;  ///< IOC / market orders that cross the spread
    int pct_iceberg = 3;
    int pct_fok = 1;
    int pct_post_only = 5;
    /// Limit orders land within this many ticks of the mid (skewed towards the touch).
    int max_ticks_from_mid = 40;
};

/// Generates a realistic synthetic session: a random-walk mid price, orders clustered near
/// the touch, heavy cancel traffic (most real order-book messages are cancels), occasional
/// marketable orders, icebergs and amends. Deterministic for a given seed.
class OrderFlowGenerator {
  public:
    OrderFlowGenerator(FlowProfile profile, std::uint64_t seed);
    [[nodiscard]] Command next();
    /// Feed back the events the last command caused, so cancels and amends target orders
    /// that are really still resting (as a trading firm's order manager would).
    void observe(std::span<const Event> events);
    [[nodiscard]] std::size_t live_orders() const noexcept { return live_.size(); }

  private:
    struct LiveOrder {
        std::size_t pos;
        Qty remaining;
    };
    [[nodiscard]] Command new_order();
    [[nodiscard]] OrderId pick_live();
    void add_live(OrderId id, Qty qty);
    void drop_live(OrderId id);

    FlowProfile profile_;
    TickTable ticks_;
    SplitMix64 rng_;
    double mid_;
    OrderId next_id_ = 1;
    std::vector<OrderId> live_;  ///< ids believed to be resting, for O(1) random picks
    std::unordered_map<OrderId, LiveOrder> info_;
};

/// Generates `n` commands with feedback from a scratch book built from `book`, so the session
/// is realistic. The result can then be replayed (and timed) against any fresh book.
[[nodiscard]] std::vector<Command> generate_session(const FlowProfile& profile, std::uint64_t seed,
                                                    std::size_t n, const BookConfig& book);

}  // namespace lob
