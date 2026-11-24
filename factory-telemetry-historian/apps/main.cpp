#include <charconv>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <string>
#include <string_view>
#include <vector>

#include "historian/analysis.hpp"
#include "historian/ingest.hpp"
#include "historian/simulator.hpp"
#include "historian/store.hpp"

namespace {

using historian::Error;
using historian::Store;

constexpr const char* kUsage = R"(usage: historian <command> [options]
  simulate   --out FILE [--machines N] [--seconds N] [--seed N]
  ingest     --db DIR --in FILE [--quarantine FILE] [--parsers N] [--no-sync] [--xor-only]
  query      --db DIR --series M/SENSOR [--from T] [--to T] [--bucket SECONDS]
  excursions --db DIR --series M/SENSOR --trip X --reset Y [--min-seconds N]
  gaps       --db DIR --series M/SENSOR [--max-gap SECONDS]
  compact    --db DIR [--full] [--expire-before T]
  stats      --db DIR
  verify     --db DIR
T is epoch milliseconds or ISO-8601 UTC, e.g. 2026-11-02T06:00:00Z
)";

/// `--key value` options plus bare flags.
class Arguments {
  public:
    Arguments(int argc, char** argv) {
        for (int i = 2; i < argc; ++i) {
            const std::string key = argv[i];
            const bool has_value = i + 1 < argc && !std::string_view(argv[i + 1]).starts_with("--");
            values_[key] = has_value ? argv[++i] : "";
        }
    }
    [[nodiscard]] bool has(const std::string& key) const { return values_.contains(key); }
    [[nodiscard]] std::string text(const std::string& key, const std::string& fallback = "") const {
        const auto it = values_.find(key);
        return it == values_.end() ? fallback : it->second;
    }
    template <typename T>
    [[nodiscard]] T number(const std::string& key, T fallback) const {
        const auto it = values_.find(key);
        if (it == values_.end()) {
            return fallback;
        }
        if constexpr (std::is_floating_point_v<T>) {
            return static_cast<T>(std::strtod(it->second.c_str(), nullptr));
        } else {
            T value = fallback;
            const char* end = it->second.data() + it->second.size();
            const auto parsed = std::from_chars(it->second.data(), end, value);
            return parsed.ec == std::errc{} && parsed.ptr == end ? value : fallback;
        }
    }
    [[nodiscard]] historian::TimestampMs time(const std::string& key,
                                              historian::TimestampMs fallback) const {
        return historian::parse_timestamp(text(key)).value_or(fallback);
    }

  private:
    std::map<std::string, std::string> values_;
};

int fail(const Error& error) {
    std::cerr << "error (" << historian::to_string(error.code) << "): " << error.message << '\n';
    return 1;
}

double seconds_since(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

int simulate(const Arguments& args) {
    std::ofstream out(args.text("--out"));
    if (!out) {
        return fail({historian::ErrorCode::InvalidArgument, "simulate needs a writable --out"});
    }
    historian::SimulationConfig config;
    config.machines = args.number("--machines", config.machines);
    config.seconds = args.number("--seconds", config.seconds);
    config.seed = args.number("--seed", config.seed);
    const auto r = historian::simulate(out, config);
    std::cout << "lines=" << r.lines << " late=" << r.late << " duplicates=" << r.duplicates
              << " corrupted=" << r.corrupted << " dropped=" << r.dropped << '\n';
    return 0;
}

int ingest(Store& store, const Arguments& args) {
    std::ifstream in(args.text("--in"));
    std::ofstream quarantine(args.text("--quarantine", "quarantine.csv"));
    if (!in || !quarantine) {
        return fail({historian::ErrorCode::InvalidArgument, "cannot open input or quarantine"});
    }
    historian::IngestOptions options;
    options.parsers = args.number("--parsers", options.parsers);
    const auto start = std::chrono::steady_clock::now();
    const auto report = historian::ingest_csv(in, store, quarantine, options);
    if (!report) {
        return fail(report.error());
    }
    const double elapsed = seconds_since(start);
    if (auto s = store.flush(); !s.ok()) {
        return fail(s.error());
    }
    const auto& r = report.value();
    std::printf("lines=%llu accepted=%llu rejected=%llu in %.2fs (%.2fM lines/s)\n",
                static_cast<unsigned long long>(r.lines),
                static_cast<unsigned long long>(r.accepted),
                static_cast<unsigned long long>(r.rejected), elapsed,
                static_cast<double>(r.lines) / elapsed / 1e6);
    for (std::size_t i = 0; i < r.by_reason.size(); ++i) {
        std::printf("  quarantined %-15s %llu\n",
                    historian::to_string(static_cast<historian::RejectReason>(i)),
                    static_cast<unsigned long long>(r.by_reason[i]));
    }
    return 0;
}

constexpr auto kMin = std::numeric_limits<historian::TimestampMs>::min();
constexpr auto kMax = std::numeric_limits<historian::TimestampMs>::max();

int query(const Store& store, const Arguments& args) {
    historian::QueryStats stats;
    const auto start = std::chrono::steady_clock::now();
    const auto result =
        store.aggregate(args.text("--series"), args.time("--from", kMin), args.time("--to", kMax),
                        args.number("--bucket", std::int64_t{3600}) * 1000, &stats);
    const double elapsed = seconds_since(start);
    if (!result) {
        return fail(result.error());
    }
    std::printf("%-24s %8s %10s %10s %10s %10s\n", "bucket", "count", "min", "mean", "max", "last");
    for (const auto& b : result.value()) {
        std::printf("%-24s %8llu %10.2f %10.2f %10.2f %10.2f\n",
                    historian::format_timestamp(b.start).c_str(),
                    static_cast<unsigned long long>(b.count), b.min, b.mean(), b.max, b.last);
    }
    std::printf("blocks: %zu from index, %zu decoded, %zu pruned (%.3f ms)\n",
                stats.blocks_from_index, stats.blocks_decoded, stats.blocks_pruned, elapsed * 1e3);
    return 0;
}

int excursions(const Store& store, const Arguments& args) {
    const auto samples = store.scan(args.text("--series"), kMin, kMax);
    if (!samples) {
        return fail(samples.error());
    }
    historian::ExcursionRule rule;
    rule.trip = args.number("--trip", 0.0);
    rule.reset = args.number("--reset", rule.trip);
    rule.min_duration = args.number("--min-seconds", std::int64_t{0}) * 1000;
    for (const auto& e : historian::find_excursions(samples.value(), rule)) {
        std::printf("%s -> %s  %6.1f min  peak %.2f\n", historian::format_timestamp(e.from).c_str(),
                    historian::format_timestamp(e.to).c_str(),
                    static_cast<double>(e.to - e.from) / 60000.0, e.peak);
    }
    return 0;
}

int gaps(const Store& store, const Arguments& args) {
    const auto samples = store.scan(args.text("--series"), kMin, kMax);
    if (!samples) {
        return fail(samples.error());
    }
    const auto found =
        historian::find_gaps(samples.value(), args.number("--max-gap", std::int64_t{5}) * 1000);
    for (const auto& g : found) {
        std::printf("%s  silent for %.1f s\n", historian::format_timestamp(g.from).c_str(),
                    static_cast<double>(g.to - g.from) / 1000.0);
    }
    std::printf("%zu gaps\n", found.size());
    return 0;
}

int compact(Store& store, const Arguments& args) {
    historian::CompactionOptions options;
    options.full = args.has("--full");
    options.expire_before = historian::parse_timestamp(args.text("--expire-before"));
    if (args.has("--expire-before") && !options.expire_before) {
        return fail({historian::ErrorCode::InvalidArgument, "bad --expire-before"});
    }
    const auto start = std::chrono::steady_clock::now();
    const auto report = store.compact(options);
    if (!report) {
        return fail(report.error());
    }
    const auto& r = report.value();
    std::printf("merged %zu segments: %llu -> %llu samples, %llu -> %llu bytes (%.2fs)\n",
                r.segments_in, static_cast<unsigned long long>(r.samples_in),
                static_cast<unsigned long long>(r.samples_out),
                static_cast<unsigned long long>(r.bytes_in),
                static_cast<unsigned long long>(r.bytes_out), seconds_since(start));
    return 0;
}

int stats(const Store& store) {
    const auto result = store.stats();
    if (!result) {
        return fail(result.error());
    }
    const auto& s = result.value();
    const double per_sample = s.segment_samples == 0 ? 0.0
                                                     : static_cast<double>(s.segment_bytes) /
                                                           static_cast<double>(s.segment_samples);
    std::printf("series=%zu segments=%zu samples=%llu bytes=%llu\n", s.series, s.segments,
                static_cast<unsigned long long>(s.segment_samples),
                static_cast<unsigned long long>(s.segment_bytes));
    std::printf("bytes/sample=%.3f (16 raw, %.1fx smaller) blocks=%zu scaled-delta=%zu xor=%zu\n",
                per_sample, per_sample > 0.0 ? 16.0 / per_sample : 0.0, s.blocks, s.scaled_blocks,
                s.blocks - s.scaled_blocks);
    const auto& r = store.recovery();
    std::printf("recovery: %llu samples replayed, torn tail: %s, orphans removed: %zu\n",
                static_cast<unsigned long long>(r.samples_replayed), r.torn_tail ? "yes" : "no",
                r.orphans_removed);
    return 0;
}

int run(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << kUsage;
        return 2;
    }
    const std::string_view command = argv[1];
    const Arguments args(argc, argv);
    if (command == "simulate") {
        return simulate(args);
    }
    if (!args.has("--db")) {
        std::cerr << kUsage;
        return 2;
    }
    historian::StoreOptions options;
    options.sync_wal = !args.has("--no-sync");
    options.codec =
        args.has("--xor-only") ? historian::CodecChoice::XorOnly : historian::CodecChoice::Auto;
    auto store = Store::open(args.text("--db"), options);
    if (!store) {
        return fail(store.error());
    }
    Store& db = *store.value();
    if (command == "ingest") return ingest(db, args);
    if (command == "query") return query(db, args);
    if (command == "excursions") return excursions(db, args);
    if (command == "gaps") return gaps(db, args);
    if (command == "compact") return compact(db, args);
    if (command == "stats") return stats(db);
    if (command == "verify") {
        const auto s = db.verify();
        if (!s.ok()) {
            return fail(s.error());
        }
        std::cout << "all blocks verified\n";
        return 0;
    }
    std::cerr << kUsage;
    return 2;
}

}  // namespace

int main(int argc, char** argv) { return run(argc, argv); }
