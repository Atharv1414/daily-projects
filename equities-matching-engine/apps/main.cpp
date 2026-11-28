// tmatch: command-line front end for the Thamesgate MTF matching engine.
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

#include "lob/exchange.hpp"
#include "lob/order_flow.hpp"

namespace {

using namespace lob;

constexpr const char* kUsage = R"(tmatch - Thamesgate MTF order book and matching engine

usage:
  tmatch demo                                   scripted trading day with auctions
  tmatch simulate [--orders N] [--seed S] [--journal FILE]
  tmatch replay --journal FILE                  rebuild the book from a journal
  tmatch run FILE|-                             apply text commands, print every event
)";

BookConfig listing(const std::string& symbol, Price reference) {
    BookConfig cfg;
    cfg.symbol = symbol;
    cfg.reference_price = reference;
    cfg.collar_bps = 500;
    return cfg;
}

void print_depth(const OrderBook& book, std::size_t levels) {
    const DepthSnapshot d = book.depth(levels);
    std::printf("    %-24s | %-24s\n", "bids (qty @ price, orders)", "asks");
    for (std::size_t i = 0; i < std::max(d.bids.size(), d.asks.size()); ++i) {
        std::string left;
        std::string right;
        if (i < d.bids.size()) {
            left = std::to_string(d.bids[i].qty) + " @ " + format_price(d.bids[i].price) + " (" +
                   std::to_string(d.bids[i].orders) + ")";
        }
        if (i < d.asks.size()) {
            right = std::to_string(d.asks[i].qty) + " @ " + format_price(d.asks[i].price) + " (" +
                    std::to_string(d.asks[i].orders) + ")";
        }
        std::printf("    %-24s | %-24s\n", left.c_str(), right.c_str());
    }
}

int apply_lines(Exchange& ex, const std::vector<std::string>& lines, bool echo) {
    int errors = 0;
    for (const std::string& line : lines) {
        if (line.empty() || line[0] == '#') {
            if (echo && !line.empty()) std::printf("\n%s\n", line.c_str());
            continue;
        }
        auto cmd = parse_command(line);
        if (!cmd) {
            std::fprintf(stderr, "error: %s in: %s\n", cmd.error().c_str(), line.c_str());
            ++errors;
            continue;
        }
        if (echo) std::printf("> %s\n", line.c_str());
        for (const Event& e : ex.apply(cmd.value())) {
            if (echo) std::printf("    %s\n", describe(e).c_str());
        }
    }
    return errors;
}

int demo() {
    Exchange ex;
    ex.list(listing("TGX", 123450));  // previous close 1234.50p
    const std::vector<std::string> script = {
        "# 07:50 opening auction call: orders collect, nothing trades",
        "AUCTION sym=TGX",
        "NEW sym=TGX id=1 owner=1 side=B px=1236.00 qty=4000",
        "NEW sym=TGX id=2 owner=2 side=B px=1235.00 qty=3000",
        "NEW sym=TGX id=3 owner=3 side=S px=1234.00 qty=2500",
        "NEW sym=TGX id=4 owner=4 side=S px=1235.00 qty=3500",
        "NEW sym=TGX id=5 owner=5 side=B type=MKT qty=1000",
        "NEW sym=TGX id=6 owner=6 side=S px=1237.00 qty=2000",
        "# 08:00 uncross at the volume-maximising price",
        "UNCROSS sym=TGX",
        "# continuous trading: an iceberg shows 500 of 3000",
        "NEW sym=TGX id=7 owner=7 side=S type=ICE px=1235.50 qty=3000 peak=500",
        "NEW sym=TGX id=8 owner=8 side=S px=1235.50 qty=400",
        "NEW sym=TGX id=9 owner=9 side=B px=1235.50 qty=1200 tif=IOC",
        "# post-only that would cross is rejected; FOK too big is killed",
        "NEW sym=TGX id=10 owner=2 side=B px=1236.00 qty=100 post=1",
        "NEW sym=TGX id=11 owner=2 side=B px=1235.50 qty=99999 tif=FOK",
        "# self-trade prevention: owner 7 buys into its own iceberg",
        "NEW sym=TGX id=12 owner=7 side=B px=1235.50 qty=300 stp=CI",
        "# amend: size-down keeps priority, price change loses it",
        "NEW sym=TGX id=13 owner=3 side=B px=1233.00 qty=1000",
        "NEW sym=TGX id=14 owner=4 side=B px=1233.00 qty=800",
        "AMD sym=TGX id=13 px=1233.00 qty=600",
        "AMD sym=TGX id=14 px=1233.50 qty=800",
        "# a large market sell runs into the 5% collar: volatility auction",
        "NEW sym=TGX id=15 owner=5 side=B px=1170.00 qty=3000",
        "NEW sym=TGX id=16 owner=6 side=S type=MKT qty=9000",
        "# during the auction, buyers step in and the price is discovered, not dumped",
        "NEW sym=TGX id=17 owner=8 side=B px=1215.00 qty=6000",
        "NEW sym=TGX id=18 owner=9 side=S px=1225.00 qty=1500",
        "UNCROSS sym=TGX",
    };
    const int errors = apply_lines(ex, script, true);
    const OrderBook& book = *ex.book("TGX");
    std::printf("\nclosing depth:\n");
    print_depth(book, 5);
    std::printf("\n%s", ex.market_data("TGX")->summary("TGX").c_str());
    const std::string inv = book.check_invariants();
    std::printf("invariants: %s\n", inv.empty() ? "ok" : inv.c_str());
    return errors == 0 && inv.empty() ? 0 : 1;
}

int simulate(std::size_t orders, std::uint64_t seed, const std::string& journal) {
    Exchange ex;
    FlowProfile profile;
    ex.list(listing(profile.symbol, profile.start_mid));
    if (!journal.empty()) {
        std::filesystem::remove(journal);
        ex.attach_journal(std::make_unique<JournalWriter>(journal));
    }
    const auto t0 = std::chrono::steady_clock::now();
    const std::vector<Command> commands =
        generate_session(profile, seed, orders, listing(profile.symbol, profile.start_mid));
    const auto t1 = std::chrono::steady_clock::now();
    std::size_t events = 0;
    for (const Command& c : commands) events += ex.apply(c).size();
    const auto t2 = std::chrono::steady_clock::now();
    const auto ms = [](auto a, auto b) {
        return std::chrono::duration<double, std::milli>(b - a).count();
    };
    const OrderBook& book = *ex.book(profile.symbol);
    std::printf(
        "generated %zu commands in %.0f ms, matched in %.0f ms (%.2f M commands/s), "
        "%zu events\n",
        orders, ms(t0, t1), ms(t1, t2), static_cast<double>(orders) / ms(t1, t2) / 1000.0, events);
    std::printf("book: %zu resting orders on %zu bid / %zu ask levels, phase %s\n",
                book.resting_orders(), book.bid_levels(), book.ask_levels(),
                std::string(to_string(book.phase())).c_str());
    print_depth(book, 5);
    std::printf("%s", ex.market_data(profile.symbol)->summary(profile.symbol).c_str());
    std::printf("state hash %016llx\n", static_cast<unsigned long long>(ex.state_hash()));
    const std::string inv = book.check_invariants();
    std::printf("invariants: %s\n", inv.empty() ? "ok" : inv.c_str());
    return inv.empty() ? 0 : 1;
}

int replay_cmd(const std::string& journal) {
    Exchange ex;
    FlowProfile profile;
    ex.list(listing(profile.symbol, profile.start_mid));
    const auto t0 = std::chrono::steady_clock::now();
    auto result = replay(ex, journal);
    const auto t1 = std::chrono::steady_clock::now();
    if (!result) {
        std::fprintf(stderr, "replay failed: %s\n", result.error().c_str());
        return 1;
    }
    std::printf("replayed %llu commands in %.0f ms\n",
                static_cast<unsigned long long>(result.value()),
                std::chrono::duration<double, std::milli>(t1 - t0).count());
    std::printf("%s", ex.market_data(profile.symbol)->summary(profile.symbol).c_str());
    std::printf("state hash %016llx\n", static_cast<unsigned long long>(ex.state_hash()));
    return 0;
}

int run_file(const std::string& path) {
    std::vector<std::string> lines;
    std::string line;
    if (path == "-") {
        while (std::getline(std::cin, line)) lines.push_back(line);
    } else {
        std::ifstream in(path);
        if (!in) {
            std::fprintf(stderr, "cannot open %s\n", path.c_str());
            return 1;
        }
        while (std::getline(in, line)) lines.push_back(line);
    }
    Exchange ex;
    ex.list(listing("TGX", 123450));
    return apply_lines(ex, lines, true) == 0 ? 0 : 1;
}

}  // namespace

int main(int argc, char** argv) {
    const std::vector<std::string_view> args(argv + 1, argv + argc);
    if (args.empty() || args[0] == "-h" || args[0] == "--help") {
        std::fputs(kUsage, stdout);
        return args.empty() ? 1 : 0;
    }
    const auto option = [&](std::string_view name, std::string fallback) {
        for (std::size_t i = 1; i + 1 < args.size(); ++i) {
            if (args[i] == name) return std::string(args[i + 1]);
        }
        return fallback;
    };
    try {
        if (args[0] == "demo") return demo();
        if (args[0] == "simulate") {
            return simulate(std::stoul(option("--orders", "1000000")),
                            std::stoull(option("--seed", "42")), option("--journal", ""));
        }
        if (args[0] == "replay") return replay_cmd(option("--journal", "session.journal"));
        if (args[0] == "run" && args.size() >= 2) return run_file(std::string(args[1]));
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
    std::fputs(kUsage, stderr);
    return 1;
}
