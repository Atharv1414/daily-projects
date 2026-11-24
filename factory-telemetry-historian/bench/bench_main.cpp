#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

#include "historian/codec.hpp"
#include "historian/ingest.hpp"
#include "historian/simulator.hpp"
#include "historian/store.hpp"

namespace {

using Clock = std::chrono::steady_clock;

double elapsed(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

historian::Store& unwrap(historian::Result<std::unique_ptr<historian::Store>>& store) {
    if (!store) {
        std::fprintf(stderr, "open failed: %s\n", store.error().message.c_str());
        std::exit(1);
    }
    return *store.value();
}

}  // namespace

int main() {
    namespace fs = std::filesystem;
    const fs::path root = fs::temp_directory_path() / "historian_bench";
    fs::remove_all(root);
    std::stringstream csv;
    const auto sim = historian::simulate(csv, {.machines = 20, .seconds = 21'600});
    const std::string text = csv.str();
    std::printf("dataset: %llu lines, %.1f MB CSV\n", static_cast<unsigned long long>(sim.lines),
                static_cast<double>(text.size()) / 1e6);

    for (const unsigned parsers : {1U, 2U, 4U}) {
        historian::StoreOptions options;
        options.sync_wal = false;
        auto store = historian::Store::open(root / ("p" + std::to_string(parsers)), options);
        std::istringstream in(text);
        std::ostringstream quarantine;
        const auto start = Clock::now();
        const auto report =
            historian::ingest_csv(in, unwrap(store), quarantine, {.parsers = parsers});
        if (!report) {
            return 1;
        }
        std::printf("ingest, %u parser(s): %.2fM lines/s\n", parsers,
                    static_cast<double>(report.value().lines) / elapsed(start) / 1e6);
    }

    for (const auto choice : {historian::CodecChoice::XorOnly, historian::CodecChoice::Auto}) {
        const bool automatic = choice == historian::CodecChoice::Auto;
        historian::StoreOptions options;
        options.sync_wal = false;
        options.codec = choice;
        auto store = historian::Store::open(root / (automatic ? "auto" : "xor"), options);
        auto& db = unwrap(store);
        std::istringstream in(text);
        std::ostringstream quarantine;
        if (!historian::ingest_csv(in, db, quarantine) || !db.flush().ok() ||
            !db.compact({.full = true, .expire_before = {}})) {
            return 1;
        }
        const auto stats = db.stats();
        if (!stats) {
            return 1;
        }
        std::printf("codec %-9s %.3f bytes/sample (%.1f MB)\n", automatic ? "auto:" : "xor only:",
                    static_cast<double>(stats.value().segment_bytes) /
                        static_cast<double>(stats.value().segment_samples),
                    static_cast<double>(stats.value().segment_bytes) / 1e6);
        if (!automatic) {
            continue;
        }
        constexpr auto kMin = std::numeric_limits<historian::TimestampMs>::min();
        constexpr auto kMax = std::numeric_limits<historian::TimestampMs>::max();
        auto start = Clock::now();
        std::size_t decoded = 0;
        for (const auto& name : db.series()) {
            const auto samples = db.scan(name, kMin, kMax);
            decoded += samples ? samples.value().size() : 0;
        }
        std::printf("full scan: %.1fM samples/s\n",
                    static_cast<double>(decoded) / elapsed(start) / 1e6);
        for (const std::int64_t width :
             {std::int64_t{60}, std::int64_t{3600}, std::int64_t{86400}}) {
            historian::QueryStats total;
            start = Clock::now();
            constexpr int kRepeats = 20;
            for (int i = 0; i < kRepeats; ++i) {
                for (const auto& name : db.series()) {
                    historian::QueryStats one;
                    const auto result = db.aggregate(name, kMin, kMax, width * 1000, &one);
                    if (!result) {
                        return 1;
                    }
                    total.blocks_from_index += one.blocks_from_index;
                    total.blocks_decoded += one.blocks_decoded;
                }
            }
            const double runs =
                static_cast<double>(kRepeats) * static_cast<double>(db.series().size());
            std::printf("aggregate %5llds buckets: %.3f ms/query, %.0f%% of blocks from index\n",
                        static_cast<long long>(width), elapsed(start) / runs * 1e3,
                        100.0 * static_cast<double>(total.blocks_from_index) /
                            static_cast<double>(total.blocks_from_index + total.blocks_decoded));
        }
    }

    historian::StoreOptions durable;
    auto store = historian::Store::open(root / "fsync", durable);
    auto& db = unwrap(store);
    const auto start = Clock::now();
    constexpr int kBatches = 200;
    for (int b = 0; b < kBatches; ++b) {
        std::vector<historian::Point> batch;
        for (int i = 0; i < 1000; ++i) {
            batch.push_back({"press-01/temp_c", {b * 1000 + i, 60.0}});
        }
        if (!db.append(batch).ok()) {
            return 1;
        }
    }
    std::printf("durable append (fsync per 1,000-sample batch): %.2fM samples/s\n",
                kBatches * 1000 / elapsed(start) / 1e6);
    fs::remove_all(root);
    return 0;
}
