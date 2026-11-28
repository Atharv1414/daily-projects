#pragma once

#include <optional>
#include <span>
#include <vector>

#include "lob/types.hpp"

namespace lob {

/// Aggregated interest at one price for the uncross calculation. Market orders use
/// kMarketBuyPrice / kMarketSellPrice so that they are always executable.
struct AuctionInterest {
    Price price;
    Qty qty;
};

struct UncrossResult {
    Price price;
    Qty volume;     ///< shares that trade at `price`
    Qty imbalance;  ///< |buy - sell| executable at `price` (the surplus left behind)
    Side surplus;   ///< which side has the surplus (Buy if equal)
};

/// Finds the auction clearing price with the usual European rules, applied in order:
///   1. maximise executable volume;
///   2. then minimise the surplus (imbalance);
///   3. then, if the surplus is all on one side at every remaining price, pick the highest
///      price for a buy surplus and the lowest for a sell surplus (market pressure);
///   4. then the price closest to the reference price;
///   5. then the lower price (a fixed, documented tie-break so results are deterministic).
/// Returns std::nullopt when nothing can trade.
///
/// `bids` and `asks` may be in any order and may contain repeated prices.
[[nodiscard]] std::optional<UncrossResult> compute_uncross(std::span<const AuctionInterest> bids,
                                                           std::span<const AuctionInterest> asks,
                                                           Price reference);

}  // namespace lob
