#pragma once

#include <cstdint>
#include <vector>

#include "lob/order_pool.hpp"
#include "lob/types.hpp"

namespace lob {

/// All orders at one price, oldest first.
struct PriceLevel {
    Price price = 0;
    Qty visible = 0;  ///< sum of visible quantity (what market data shows)
    Qty hidden = 0;   ///< sum of iceberg reserves (never published)
    std::uint32_t count = 0;
    NodeIndex head = kNullNode;
    NodeIndex tail = kNullNode;
};

/// One side of the book as a sorted vector of levels with the BEST level at the back.
///
/// Most activity happens within a few ticks of the touch, so inserts and removals near the
/// back move very few elements, and the best level is a single `back()` with no pointer
/// chasing. A balanced tree (std::map) has better worst-case inserts far from the touch but
/// worse constant factors on the hot path; see docs/ARCHITECTURE.md for the measurements.
class PriceLadder {
  public:
    explicit PriceLadder(Side side) : side_(side) {}

    [[nodiscard]] Side side() const noexcept { return side_; }
    [[nodiscard]] bool empty() const noexcept { return levels_.empty(); }
    [[nodiscard]] std::size_t depth() const noexcept { return levels_.size(); }

    [[nodiscard]] PriceLevel& best() noexcept { return levels_.back(); }
    [[nodiscard]] const PriceLevel& best() const noexcept { return levels_.back(); }

    /// Level `i` counted from the best (0 = best).
    [[nodiscard]] const PriceLevel& level_from_best(std::size_t i) const noexcept {
        return levels_[levels_.size() - 1 - i];
    }
    [[nodiscard]] PriceLevel& level_from_best(std::size_t i) noexcept {
        return levels_[levels_.size() - 1 - i];
    }

    /// True if `a` is a better price than `b` on this side.
    [[nodiscard]] bool better(Price a, Price b) const noexcept {
        return side_ == Side::Buy ? a > b : a < b;
    }

    /// Append `idx` to the back of the queue at its price, creating the level if needed.
    void push_back(OrderPool& pool, NodeIndex idx);
    /// Unlink `idx` from its level, removing the level if it becomes empty.
    void unlink(OrderPool& pool, NodeIndex idx);
    /// Move `idx` to the back of its own level (used when an iceberg refreshes).
    void move_to_back(OrderPool& pool, NodeIndex idx);
    /// Pointer to the level at `price`, or nullptr.
    [[nodiscard]] PriceLevel* find(Price price) noexcept;
    /// Remove the best level (must be empty of orders).
    void pop_best() noexcept { levels_.pop_back(); }

    [[nodiscard]] Qty total_visible() const noexcept;

  private:
    /// Position of the first level that is not worse than `price` (lower_bound in ladder order).
    [[nodiscard]] std::size_t position(Price price) const noexcept;

    Side side_;
    std::vector<PriceLevel> levels_;
};

}  // namespace lob
