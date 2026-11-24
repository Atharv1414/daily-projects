#include "historian/analysis.hpp"

#include <algorithm>
#include <limits>
#include <optional>

namespace historian {

std::vector<Gap> find_gaps(std::span<const Sample> samples, std::int64_t max_gap) {
    std::vector<Gap> gaps;
    for (std::size_t i = 1; i < samples.size(); ++i) {
        if (samples[i].ts - samples[i - 1].ts > max_gap) {
            gaps.push_back({samples[i - 1].ts, samples[i].ts});
        }
    }
    return gaps;
}

std::vector<Excursion> find_excursions(std::span<const Sample> samples, const ExcursionRule& rule) {
    std::vector<Excursion> found;
    std::optional<Excursion> open;
    const auto close = [&] {
        if (open && open->to - open->from >= rule.min_duration) {
            found.push_back(*open);
        }
        open.reset();
    };
    for (const Sample& s : samples) {
        if (open && (s.ts - open->to > rule.max_gap || s.value < rule.reset)) {
            close();
        }
        if (open) {
            open->to = s.ts;
            open->peak = std::max(open->peak, s.value);
            ++open->samples;
        } else if (s.value > rule.trip) {
            open = Excursion{s.ts, s.ts, s.value, 1};
        }
    }
    close();
    return found;
}

double time_weighted_mean(std::span<const Sample> samples, std::int64_t max_hold) {
    if (samples.empty()) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    double weighted = 0.0;
    double total = 0.0;
    for (std::size_t i = 1; i < samples.size(); ++i) {
        const auto hold =
            static_cast<double>(std::min(samples[i].ts - samples[i - 1].ts, max_hold));
        weighted += samples[i - 1].value * hold;
        total += hold;
    }
    return total > 0.0 ? weighted / total : samples.back().value;
}

}  // namespace historian
