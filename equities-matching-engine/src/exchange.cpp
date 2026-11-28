#include "lob/exchange.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <variant>
#include <vector>

namespace lob {

namespace {

template <class... Fs>
struct Overloaded : Fs... {
    using Fs::operator()...;
};
template <class... Fs>
Overloaded(Fs...) -> Overloaded<Fs...>;

OrderId order_id_of(const Command& c) {
    return std::visit(Overloaded{
                          [](const SubmitCmd& s) { return s.order.id; },
                          [](const CancelCmd& s) { return s.request.id; },
                          [](const AmendCmd& s) { return s.request.id; },
                          [](const SessionCmd&) { return OrderId{0}; },
                      },
                      c);
}

}  // namespace

Exchange::Exchange(PreTradeRisk risk) : risk_(std::move(risk)) { scratch_.reserve(4); }

void Exchange::list(BookConfig config) {
    const std::string symbol = config.symbol;
    if (listings_.contains(symbol)) throw std::invalid_argument("already listed: " + symbol);
    Listing listing;
    listing.book = std::make_unique<OrderBook>(std::move(config));
    listings_.emplace(symbol, std::move(listing));
}

void Exchange::attach_journal(std::unique_ptr<JournalWriter> journal) {
    journal_ = std::move(journal);
}

OrderBook* Exchange::book(const std::string& symbol) {
    const auto it = listings_.find(symbol);
    return it == listings_.end() ? nullptr : it->second.book.get();
}

const OrderBook* Exchange::book(const std::string& symbol) const {
    const auto it = listings_.find(symbol);
    return it == listings_.end() ? nullptr : it->second.book.get();
}

const MarketDataRecorder* Exchange::market_data(const std::string& symbol) const {
    const auto it = listings_.find(symbol);
    return it == listings_.end() ? nullptr : &it->second.md;
}

std::vector<std::string> Exchange::symbols() const {
    std::vector<std::string> out;
    out.reserve(listings_.size());
    for (const auto& [symbol, listing] : listings_) out.push_back(symbol);
    return out;
}

std::uint64_t Exchange::state_hash() const noexcept {
    std::uint64_t h = 1469598103934665603ull;
    for (const auto& [symbol, listing] : listings_) {
        h ^= listing.book->state_hash();
        h *= 1099511628211ull;
    }
    return h;
}

std::span<const Event> Exchange::apply(const Command& command) {
    ++applied_;
    const auto it = listings_.find(symbol_of(command));
    if (it == listings_.end()) {
        scratch_.assign(1, Rejected{order_id_of(command), RejectReason::UnknownSymbol});
        return scratch_;
    }
    Listing& listing = it->second;
    OrderBook& book = *listing.book;

    // Risk runs before journaling: a risk reject is a gateway decision, not a book event, so
    // it does not need to be replayed. Everything that reaches the book is journaled first.
    if (const auto* submit = std::get_if<SubmitCmd>(&command)) {
        const RiskDecision decision = risk_.check(submit->order, book.reference_price(),
                                                  book.open_orders(submit->order.owner));
        if (!decision.allowed) {
            scratch_.assign(1, Rejected{submit->order.id, RejectReason::RiskLimitBreached});
            listing.md.on_events(scratch_);
            return scratch_;
        }
    }
    if (journal_) journal_->append(command);

    const std::vector<Event>& events = std::visit(
        Overloaded{
            [&](const SubmitCmd& s) -> const std::vector<Event>& { return book.submit(s.order); },
            [&](const CancelCmd& s) -> const std::vector<Event>& { return book.cancel(s.request); },
            [&](const AmendCmd& s) -> const std::vector<Event>& { return book.amend(s.request); },
            [&](const SessionCmd& s) -> const std::vector<Event>& {
                switch (s.kind) {
                    case SessionCmd::Kind::StartAuction:
                        return book.start_auction();
                    case SessionCmd::Kind::Uncross:
                        return book.uncross();
                    case SessionCmd::Kind::Halt:
                        return book.halt();
                    case SessionCmd::Kind::Resume:
                        break;
                }
                return book.resume();
            },
        },
        command);
    listing.md.on_events(events);
    return events;
}

Result<std::uint64_t> replay(Exchange& exchange, const std::filesystem::path& journal) {
    auto read = read_journal(journal);
    if (!read) return Result<std::uint64_t>::failure(read.error());
    for (const Command& c : read.value().commands) exchange.apply(c);
    return static_cast<std::uint64_t>(read.value().commands.size());
}

// ---- MatchingThread -------------------------------------------------------------------------

MatchingThread::MatchingThread(Exchange& exchange, std::size_t ring_capacity, Sink sink)
    : exchange_(exchange), ring_(ring_capacity), sink_(std::move(sink)) {
    worker_ = std::jthread([this](std::stop_token stop) { run(stop); });
}

MatchingThread::~MatchingThread() { drain_and_stop(); }

bool MatchingThread::try_submit(Command command) {
    if (!ring_.try_push(std::move(command))) return false;
    submitted_.fetch_add(1, std::memory_order_release);
    return true;
}

void MatchingThread::submit(Command command) {
    // try_push takes its argument by value, so each attempt copies and a failed attempt
    // leaves `command` intact for the retry.
    while (!ring_.try_push(command)) std::this_thread::yield();
    submitted_.fetch_add(1, std::memory_order_release);
}

void MatchingThread::drain_and_stop() {
    if (!worker_.joinable()) return;
    while (processed_.load(std::memory_order_acquire) <
           submitted_.load(std::memory_order_acquire)) {
        std::this_thread::yield();
    }
    worker_.request_stop();
    worker_.join();
}

void MatchingThread::run(std::stop_token stop) {
    EventBatch batch;
    std::uint64_t seq = 0;
    while (true) {
        auto command = ring_.try_pop();
        if (!command) {
            if (stop.stop_requested()) break;
            std::this_thread::yield();
            continue;
        }
        const auto events = exchange_.apply(*command);
        if (sink_) {
            batch.command_seq = ++seq;
            batch.symbol = symbol_of(*command);
            batch.events.assign(events.begin(), events.end());
            sink_(batch);
        }
        processed_.fetch_add(1, std::memory_order_release);
    }
}

}  // namespace lob
