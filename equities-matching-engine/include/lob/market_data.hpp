#pragma once

#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <unordered_map>

#include "lob/types.hpp"

namespace lob {

/// Running trade statistics for one symbol, built only from the event stream (so it can sit
/// on a separate thread or process and be rebuilt from the journal).
struct TradeStats {
    std::optional<Price> open;
    std::optional<Price> high;
    std::optional<Price> low;
    std::optional<Price> last;
    Qty volume = 0;
    std::uint64_t trades = 0;
    std::uint64_t auction_trades = 0;
    /// Sum of price * qty in price units; stored as long double so VWAP stays exact enough for
    /// tens of millions of shares at four-figure pence prices.
    long double notional = 0;

    [[nodiscard]] std::optional<double> vwap() const noexcept;
};

/// Counts of everything that happened, for the end-of-day summary and the benchmark.
struct ActivityCounters {
    std::uint64_t accepted = 0;
    std::uint64_t rejected = 0;
    std::uint64_t cancelled = 0;
    std::uint64_t amended = 0;
    std::uint64_t phase_changes = 0;
    std::uint64_t stp_cancels = 0;
    std::unordered_map<std::uint8_t, std::uint64_t> rejects_by_reason;
};

class MarketDataRecorder {
  public:
    void on_events(std::span<const Event> events);
    [[nodiscard]] const TradeStats& stats() const noexcept { return stats_; }
    [[nodiscard]] const ActivityCounters& counters() const noexcept { return counters_; }
    /// Multi-line text summary used by the CLI.
    [[nodiscard]] std::string summary(const std::string& symbol) const;

  private:
    TradeStats stats_;
    ActivityCounters counters_;
};

}  // namespace lob
