#include "lob/market_data.hpp"

#include <algorithm>
#include <cstdio>
#include <sstream>

namespace lob {

std::optional<double> TradeStats::vwap() const noexcept {
    if (volume == 0) return std::nullopt;
    return static_cast<double>(notional / static_cast<long double>(volume));
}

void MarketDataRecorder::on_events(std::span<const Event> events) {
    for (const Event& e : events) {
        if (const auto* t = std::get_if<Trade>(&e)) {
            if (!stats_.open) stats_.open = t->price;
            stats_.high = stats_.high ? std::max(*stats_.high, t->price) : t->price;
            stats_.low = stats_.low ? std::min(*stats_.low, t->price) : t->price;
            stats_.last = t->price;
            stats_.volume += t->qty;
            stats_.notional +=
                static_cast<long double>(t->price) * static_cast<long double>(t->qty);
            ++stats_.trades;
            if (t->auction) ++stats_.auction_trades;
        } else if (std::holds_alternative<Accepted>(e)) {
            ++counters_.accepted;
        } else if (const auto* r = std::get_if<Rejected>(&e)) {
            ++counters_.rejected;
            ++counters_.rejects_by_reason[static_cast<std::uint8_t>(r->reason)];
        } else if (const auto* c = std::get_if<Cancelled>(&e)) {
            ++counters_.cancelled;
            if (c->reason == CancelReason::SelfTradePrevention) ++counters_.stp_cancels;
        } else if (std::holds_alternative<Amended>(e)) {
            ++counters_.amended;
        } else if (std::holds_alternative<PhaseChanged>(e)) {
            ++counters_.phase_changes;
        }
    }
}

std::string MarketDataRecorder::summary(const std::string& symbol) const {
    std::ostringstream out;
    const auto px = [](const std::optional<Price>& p) { return p ? format_price(*p) : "-"; };
    out << symbol << ": " << stats_.trades << " trades (" << stats_.auction_trades
        << " in auctions), volume " << stats_.volume << " shares\n";
    out << "  open " << px(stats_.open) << "  high " << px(stats_.high) << "  low "
        << px(stats_.low) << "  last " << px(stats_.last);
    if (const auto v = stats_.vwap()) {
        char buf[32];
        std::snprintf(buf, sizeof buf, "%.2fp", *v / static_cast<double>(kPriceUnitsPerPenny));
        out << "  VWAP " << buf;
    }
    char value[48];
    std::snprintf(value, sizeof value, "%.0f",
                  static_cast<double>(stats_.notional) / (100.0 * kPriceUnitsPerPenny));
    out << "\n  traded value GBP " << value << "\n";
    out << "  accepted " << counters_.accepted << ", rejected " << counters_.rejected
        << ", cancelled " << counters_.cancelled << " (" << counters_.stp_cancels
        << " by self-trade prevention), amended " << counters_.amended << ", phase changes "
        << counters_.phase_changes << "\n";
    std::vector<std::pair<std::uint8_t, std::uint64_t>> reasons(counters_.rejects_by_reason.begin(),
                                                                counters_.rejects_by_reason.end());
    std::sort(reasons.begin(), reasons.end());
    for (const auto& [reason, count] : reasons) {
        out << "    rejected: " << to_string(static_cast<RejectReason>(reason)) << " x" << count
            << "\n";
    }
    return out.str();
}

}  // namespace lob
