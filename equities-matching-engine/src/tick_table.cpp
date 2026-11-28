#include "lob/tick_table.hpp"

#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

namespace lob {

TickTable::TickTable(std::vector<TickBand> bands) : bands_(std::move(bands)) {
    if (bands_.empty()) throw std::invalid_argument("tick table needs at least one band");
    Price previous = 0;
    for (const auto& band : bands_) {
        if (band.tick <= 0) throw std::invalid_argument("tick size must be positive");
        if (band.upper <= previous) throw std::invalid_argument("bands must increase");
        if (previous % band.tick != 0) {
            throw std::invalid_argument("band start must lie on the band's tick");
        }
        previous = band.upper;
    }
}

TickTable TickTable::uk_liquid() {
    // 1 unit = 0.01p. Below £1 the tick is 0.01p; above £50 it is 1p.
    return TickTable({
        {10'000, 1},                               // < 100p        tick 0.01p
        {50'000, 5},                               // 100p - 500p   tick 0.05p
        {100'000, 10},                             // 500p - 1000p  tick 0.1p
        {500'000, 50},                             // 1000p - 5000p tick 0.5p
        {std::numeric_limits<Price>::max(), 100},  // >= 5000p tick 1p
    });
}

Price TickTable::tick_for(Price price) const noexcept {
    for (const auto& band : bands_) {
        if (price < band.upper) return band.tick;
    }
    return bands_.back().tick;
}

bool TickTable::is_valid(Price price) const noexcept {
    return price > 0 && price % tick_for(price) == 0;
}

Price TickTable::round_down(Price price) const noexcept {
    if (price <= 0) return 0;
    const Price tick = tick_for(price);
    return price - price % tick;
}

Price TickTable::next_up(Price price) const noexcept { return price + tick_for(price); }

}  // namespace lob
