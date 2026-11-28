#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <thread>
#include <vector>

#include "lob/command.hpp"
#include "lob/journal.hpp"
#include "lob/market_data.hpp"
#include "lob/order_book.hpp"
#include "lob/risk.hpp"
#include "lob/spsc_ring.hpp"

namespace lob {

/// Events tagged with the command that caused them.
struct EventBatch {
    std::uint64_t command_seq = 0;
    std::string symbol;
    std::vector<Event> events;
};

/// The venue: a set of order books, the pre-trade risk gateway, an optional journal and
/// per-symbol market-data recorders. Single-threaded; see MatchingThread for the threaded
/// front end.
class Exchange {
  public:
    explicit Exchange(PreTradeRisk risk = PreTradeRisk{});

    /// Lists a symbol. Throws std::invalid_argument if it is already listed.
    void list(BookConfig config);
    /// Write every command to this journal before applying it.
    void attach_journal(std::unique_ptr<JournalWriter> journal);

    /// Apply one command. Returns the events it caused (valid until the next call).
    std::span<const Event> apply(const Command& command);

    [[nodiscard]] OrderBook* book(const std::string& symbol);
    [[nodiscard]] const OrderBook* book(const std::string& symbol) const;
    [[nodiscard]] const MarketDataRecorder* market_data(const std::string& symbol) const;
    [[nodiscard]] std::vector<std::string> symbols() const;
    [[nodiscard]] std::uint64_t commands_applied() const noexcept { return applied_; }
    /// Combined hash over every book, in symbol order.
    [[nodiscard]] std::uint64_t state_hash() const noexcept;

  private:
    struct Listing {
        std::unique_ptr<OrderBook> book;
        MarketDataRecorder md;
    };
    std::map<std::string, Listing> listings_;
    PreTradeRisk risk_;
    std::unique_ptr<JournalWriter> journal_;
    std::vector<Event> scratch_;
    std::uint64_t applied_ = 0;
};

/// Rebuilds an exchange's state from a journal (same listings must be configured first).
/// Returns the number of commands replayed.
Result<std::uint64_t> replay(Exchange& exchange, const std::filesystem::path& journal);

/// Runs an Exchange on its own thread. A gateway thread pushes commands into a lock-free SPSC
/// ring; the matching thread drains it and hands each event batch to `sink` (called on the
/// matching thread). When the ring is full, submit() returns false: back-pressure is explicit
/// rather than an unbounded queue hiding a slow consumer.
class MatchingThread {
  public:
    using Sink = std::function<void(const EventBatch&)>;

    MatchingThread(Exchange& exchange, std::size_t ring_capacity, Sink sink);
    ~MatchingThread();
    MatchingThread(const MatchingThread&) = delete;
    MatchingThread& operator=(const MatchingThread&) = delete;

    [[nodiscard]] bool try_submit(Command command);
    /// Spins (yielding) until there is room. Use from exactly one producer thread.
    void submit(Command command);
    /// Waits until every submitted command has been applied, then stops the thread.
    void drain_and_stop();
    [[nodiscard]] std::uint64_t processed() const noexcept {
        return processed_.load(std::memory_order_acquire);
    }

  private:
    void run(std::stop_token stop);

    Exchange& exchange_;
    SpscRing<Command> ring_;
    Sink sink_;
    std::atomic<std::uint64_t> submitted_{0};
    std::atomic<std::uint64_t> processed_{0};
    std::jthread worker_;
};

}  // namespace lob
