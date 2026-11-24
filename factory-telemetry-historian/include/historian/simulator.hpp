#pragma once

#include <cstdint>
#include <iosfwd>

#include "historian/types.hpp"

namespace historian {

struct SimulationConfig {
    unsigned machines = 8;
    unsigned seconds = 3600;
    TimestampMs start = 1'793'577'600'000;  // 2026-11-02T00:00:00Z
    std::uint64_t seed = 42;
};

struct SimulationReport {
    std::uint64_t lines = 0;
    std::uint64_t late = 0;
    std::uint64_t duplicates = 0;
    std::uint64_t corrupted = 0;
    std::uint64_t dropped = 0;
};

/// Writes deterministic 1 Hz telemetry for six sensors per machine, with the faults a real
/// plant produces: late store-and-forward bursts, duplicate sends, corrupt lines, network
/// dropouts and a bearing that overheats.
[[nodiscard]] SimulationReport simulate(std::ostream& out, const SimulationConfig& config = {});

}  // namespace historian
