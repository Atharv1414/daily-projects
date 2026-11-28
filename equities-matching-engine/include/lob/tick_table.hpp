#pragma once

#include <span>
#include <vector>

#include "lob/types.hpp"

namespace lob {

/// One row of a tick-size table: prices below `upper` (exclusive) must be multiples of `tick`.
struct TickBand {
    Price upper;
    Price tick;
};

/// Price-banded tick sizes in the style of the MiFID II tick-size regime: the tick grows with
/// the price so that the spread in basis points stays roughly constant.
class TickTable {
  public:
    /// Bands must be strictly increasing in `upper` and every tick must be positive.
    /// Throws std::invalid_argument otherwise.
    explicit TickTable(std::vector<TickBand> bands);

    /// A simplified table for a liquid FTSE 350 share (1 unit = 0.01p).
    [[nodiscard]] static TickTable uk_liquid();

    [[nodiscard]] Price tick_for(Price price) const noexcept;
    [[nodiscard]] bool is_valid(Price price) const noexcept;
    /// Round down to the nearest valid tick (useful for generators and price collars).
    [[nodiscard]] Price round_down(Price price) const noexcept;
    /// The next valid price above `price` (which must itself be valid).
    [[nodiscard]] Price next_up(Price price) const noexcept;
    [[nodiscard]] std::span<const TickBand> bands() const noexcept { return bands_; }

  private:
    std::vector<TickBand> bands_;
};

}  // namespace lob
