// Latency and throughput benchmark. Build with the release preset:
//   cmake --preset release -DBUILD_BENCHMARKS=ON && cmake --build --preset release
//   ./build/release/tmatch_bench [commands]
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdio>
#include <deque>
#include <functional>
#include <map>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "lob/exchange.hpp"
#include "lob/order_flow.hpp"

namespace {

using namespace lob;
using Clock = std::chrono::steady_clock;

BookConfig config(const FlowProfile& p) {
    BookConfig cfg;
    cfg.symbol = p.symbol;
    cfg.reference_price = p.start_mid;
    cfg.collar_bps = 0;  // no auctions: measure pure continuous matching
    cfg.expected_orders = 1 << 20;
    return cfg;
}

double percentile(std::vector<double>& v, double q) {
    const auto k = static_cast<std::size_t>(q * static_cast<double>(v.size() - 1));
    std::nth_element(v.begin(), v.begin() + static_cast<std::ptrdiff_t>(k), v.end());
    return v[k];
}

void single_thread(std::size_t n) {
    FlowProfile profile;
    const std::vector<Command> commands = generate_session(profile, 7, n, config(profile));
    Exchange ex;
    ex.list(config(profile));

    // Warm up the pool and the caches with the first 10%, then time each command.
    const std::size_t warm = n / 10;
    for (std::size_t i = 0; i < warm; ++i) (void)ex.apply(commands[i]);
    std::vector<double> latency;
    latency.reserve(n - warm);
    std::size_t trades = 0;
    const auto start = Clock::now();
    for (std::size_t i = warm; i < n; ++i) {
        const auto t0 = Clock::now();
        const auto events = ex.apply(commands[i]);
        const auto t1 = Clock::now();
        latency.push_back(std::chrono::duration<double, std::nano>(t1 - t0).count());
        for (const auto& e : events) trades += std::holds_alternative<Trade>(e) ? 1u : 0u;
    }
    const double total_ms = std::chrono::duration<double, std::milli>(Clock::now() - start).count();
    const double measured = static_cast<double>(n - warm);
    std::printf("single thread, %zu commands (%zu trades)\n", n - warm, trades);
    std::printf("  throughput   %.2f M commands/s (including timer overhead)\n",
                measured / total_ms / 1000.0);
    std::printf("  latency ns   p50 %.0f  p90 %.0f  p99 %.0f  p99.9 %.0f  max %.0f\n",
                percentile(latency, 0.50), percentile(latency, 0.90), percentile(latency, 0.99),
                percentile(latency, 0.999), *std::max_element(latency.begin(), latency.end()));
    const OrderBook& book = *ex.book(profile.symbol);
    std::printf("  final book   %zu orders, %zu bid / %zu ask levels\n", book.resting_orders(),
                book.bid_levels(), book.ask_levels());
}

void untimed_throughput(std::size_t n) {
    FlowProfile profile;
    const std::vector<Command> commands = generate_session(profile, 7, n, config(profile));
    Exchange ex;
    ex.list(config(profile));
    const auto start = Clock::now();
    for (const Command& c : commands) (void)ex.apply(c);
    const double ms = std::chrono::duration<double, std::milli>(Clock::now() - start).count();
    std::printf("single thread, no per-command timer: %.2f M commands/s (%.0f ns/command)\n",
                static_cast<double>(n) / ms / 1000.0, ms * 1e6 / static_cast<double>(n));
}

void threaded(std::size_t n) {
    FlowProfile profile;
    std::vector<Command> commands = generate_session(profile, 7, n, config(profile));
    Exchange ex;
    ex.list(config(profile));
    std::atomic<std::size_t> events{0};
    const auto start = Clock::now();
    {
        MatchingThread mt(ex, 1 << 14, [&events](const EventBatch& b) {
            events.fetch_add(b.events.size(), std::memory_order_relaxed);
        });
        for (Command& c : commands) mt.submit(std::move(c));
        mt.drain_and_stop();
    }
    const double ms = std::chrono::duration<double, std::milli>(Clock::now() - start).count();
    std::printf("gateway thread -> SPSC ring -> matching thread: %.2f M commands/s, %zu events\n",
                static_cast<double>(n) / ms / 1000.0, events.load());
}

void ladder_vs_map() {
    // Insert and remove price levels near the touch, the common case for a book.
    constexpr int kOps = 2'000'000;
    SplitMix64 rng(3);
    std::vector<Price> prices(kOps);
    for (auto& p : prices) p = 123'450 + rng.between(-40, 40) * 50;

    OrderPool pool(1024);
    PriceLadder ladder(Side::Buy);
    std::deque<NodeIndex> live;
    auto t0 = Clock::now();
    for (int i = 0; i < kOps; ++i) {
        if (live.size() > 200) {
            ladder.unlink(pool, live.front());
            pool.release(live.front());
            live.pop_front();
        }
        const NodeIndex idx = pool.allocate();
        pool[idx].price = prices[static_cast<std::size_t>(i)];
        pool[idx].visible = 100;
        ladder.push_back(pool, idx);
        live.push_back(idx);
    }
    const double vec_ms = std::chrono::duration<double, std::milli>(Clock::now() - t0).count();

    std::map<Price, Qty, std::greater<>> tree;
    std::deque<Price> tree_live;
    t0 = Clock::now();
    for (int i = 0; i < kOps; ++i) {
        if (tree_live.size() > 200) {
            auto it = tree.find(tree_live.front());
            if ((it->second -= 100) == 0) tree.erase(it);
            tree_live.pop_front();
        }
        tree[prices[static_cast<std::size_t>(i)]] += 100;
        tree_live.push_back(prices[static_cast<std::size_t>(i)]);
    }
    const double map_ms = std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
    std::printf(
        "price levels, 2M add+remove near the touch: sorted vector %.0f ms, std::map %.0f ms\n",
        vec_ms, map_ms);
}

}  // namespace

int main(int argc, char** argv) {
    const std::size_t n = argc > 1 ? std::stoul(argv[1]) : 2'000'000;
    single_thread(n);
    untimed_throughput(n);
    threaded(n);
    ladder_vs_map();
    return 0;
}
