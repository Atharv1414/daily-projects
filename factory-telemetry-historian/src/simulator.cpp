#include "historian/simulator.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <ostream>
#include <string>
#include <vector>

namespace historian {

namespace {

/// SplitMix64. std:: distributions differ between standard libraries, and the generator must
/// produce the same file on every platform.
class Random {
  public:
    explicit Random(std::uint64_t seed) : state_(seed) {}
    double uniform() {
        state_ += 0x9E3779B97F4A7C15ULL;
        std::uint64_t z = state_;
        z = (z ^ (z >> 30U)) * 0xBF58476D1CE4E5B9ULL;
        z = (z ^ (z >> 27U)) * 0x94D049BB133111EBULL;
        z ^= z >> 31U;
        return static_cast<double>(z >> 11U) * 0x1.0p-53;
    }
    bool chance(double p) { return uniform() < p; }
    double noise(double scale) { return (uniform() + uniform() + uniform() - 1.5) * scale; }

  private:
    std::uint64_t state_;
};

std::string line(TimestampMs ts, unsigned machine, const char* sensor, int decimals, double v) {
    std::array<char, 96> buffer{};
    std::snprintf(buffer.data(), buffer.size(), "%lld,press-%02u,%s,%.*f",
                  static_cast<long long>(ts), machine + 1, sensor, decimals, v);
    return buffer.data();
}

const char* corrupt_line(std::uint64_t n) {
    constexpr std::array<const char*, 6> kBad{
        "1793577600000,press-01,temp_c",         "01/11/2026 06:00,press-02,temp_c,61.2",
        "1793577600000,PRESS 3,power_kw,40.1",   "1793577600000,press-04,humidity_pct,44",
        "1793577600000,press-05,power_kw,ERR#7", "1793577600000,press-06,temp_c,6553.5",
    };
    return kBad[n % kBad.size()];
}

}  // namespace

SimulationReport simulate(std::ostream& out, const SimulationConfig& config) {
    Random random(config.seed);
    SimulationReport report;
    out << "timestamp,machine,sensor,value\n";
    std::vector<double> temperature(config.machines, 62.0);
    std::vector<double> parts(config.machines, 0.0);
    std::vector<std::vector<std::string>> held(config.machines);  // store-and-forward buffers
    std::vector<unsigned> offline(config.machines, 0);            // seconds left offline
    const unsigned fault_machine = config.machines / 2;

    for (unsigned second = 0; second < config.seconds; ++second) {
        for (unsigned m = 0; m < config.machines; ++m) {
            const double phase = static_cast<double>(second) / 900.0 + m;
            const bool running = std::fmod(phase, 4.0) < 3.4;
            const double wear = m == fault_machine && second > config.seconds / 2
                                    ? 45.0 * (0.5 + 0.5 * std::sin(second / 300.0))
                                    : 0.0;
            const double target = (running ? 64.0 + 4.0 * std::sin(phase) : 35.0) + wear;
            temperature[m] += (target - temperature[m]) * 0.01 + random.noise(0.15);
            if (running && second % 12 == m % 12) {
                parts[m] += 1.0;
            }
            const TimestampMs ts = config.start + TimestampMs{second} * 1000 +
                                   static_cast<TimestampMs>(random.uniform() * 20.0);
            const double power = running ? 42.0 + random.noise(3.0) : 2.5;
            const std::array<std::string, 6> lines{
                line(ts, m, "temp_c", 1, temperature[m]),
                line(ts, m, "vibration_mm_s", 2,
                     running ? std::max(0.0, 2.2 + wear / 12.0 + random.noise(0.4)) : 0.05),
                line(ts, m, "spindle_rpm", 0, running ? 1480.0 + random.noise(12.0) : 0.0),
                line(ts, m, "power_kw", 6, power),
                line(ts, m, "pressure_bar", 1, running ? 182.0 + random.noise(2.0) : 12.0),
                line(ts, m, "part_count", 0, parts[m]),
            };
            if (offline[m] == 0 && random.chance(0.0003)) {
                offline[m] = 20 + static_cast<unsigned>(random.uniform() * 100.0);
            }
            for (const auto& text : lines) {
                if (random.chance(0.0005)) {
                    ++report.dropped;
                    continue;
                }
                if (offline[m] > 0) {
                    held[m].push_back(text);
                    continue;
                }
                out << text << '\n';
                ++report.lines;
                if (random.chance(0.004)) {
                    out << text << '\n';
                    ++report.lines;
                    ++report.duplicates;
                }
                if (random.chance(0.001)) {
                    out << corrupt_line(report.corrupted) << '\n';
                    ++report.lines;
                    ++report.corrupted;
                }
            }
            if (offline[m] > 0 && --offline[m] == 0) {
                for (const auto& text : held[m]) {
                    out << text << '\n';
                    ++report.lines;
                    ++report.late;
                }
                held[m].clear();
            }
        }
    }
    for (const auto& buffer : held) {  // gateways flush on shutdown
        for (const auto& text : buffer) {
            out << text << '\n';
            ++report.lines;
            ++report.late;
        }
    }
    return report;
}

}  // namespace historian
