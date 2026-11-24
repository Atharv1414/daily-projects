#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "historian/types.hpp"

namespace historian {

/// A silent stretch between two consecutive samples.
struct Gap {
    TimestampMs from = 0;
    TimestampMs to = 0;
};

/// A period above a limit.
struct Excursion {
    TimestampMs from = 0;
    TimestampMs to = 0;  ///< last sample still inside the excursion
    double peak = 0.0;
    std::size_t samples = 0;
};

struct ExcursionRule {
    double trip = 0.0;              ///< starts when value > trip
    double reset = 0.0;             ///< ends when value < reset (hysteresis)
    std::int64_t min_duration = 0;  ///< shorter excursions are noise
    std::int64_t max_gap = 60'000;  ///< a longer silence ends the excursion
};

[[nodiscard]] std::vector<Gap> find_gaps(std::span<const Sample> samples, std::int64_t max_gap);
[[nodiscard]] std::vector<Excursion> find_excursions(std::span<const Sample> samples,
                                                     const ExcursionRule& rule);

/// Mean weighted by how long each value was held. Unlike a plain mean it is not biased when a
/// sensor reports more often during faults. Holds longer than max_hold are truncated.
[[nodiscard]] double time_weighted_mean(std::span<const Sample> samples, std::int64_t max_hold);

}  // namespace historian
