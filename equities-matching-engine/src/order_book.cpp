#include "lob/order_book.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace lob {

namespace {

constexpr std::uint64_t kFnvOffset = 1469598103934665603ull;
constexpr std::uint64_t kFnvPrime = 1099511628211ull;

void fnv_mix(std::uint64_t& h, std::uint64_t value) noexcept {
    for (int i = 0; i < 8; ++i) {
        h ^= (value >> (i * 8)) & 0xFFu;
        h *= kFnvPrime;
    }
}

bool is_market_price(Price p) noexcept { return p == kMarketBuyPrice || p == kMarketSellPrice; }

}  // namespace

OrderBook::OrderBook(BookConfig config)
    : config_(std::move(config)),
      reference_(config_.reference_price),
      pool_(config_.expected_orders) {
    index_.reserve(config_.expected_orders);
    events_.reserve(64);
}

// ---- queries --------------------------------------------------------------------------------

std::optional<Price> OrderBook::best_bid() const noexcept {
    if (bids_.empty()) return std::nullopt;
    return bids_.best().price;
}

std::optional<Price> OrderBook::best_ask() const noexcept {
    if (asks_.empty()) return std::nullopt;
    return asks_.best().price;
}

std::uint32_t OrderBook::open_orders(ParticipantId owner) const {
    const auto it = open_by_owner_.find(owner);
    return it == open_by_owner_.end() ? 0u : it->second;
}

DepthSnapshot OrderBook::depth(std::size_t levels) const {
    DepthSnapshot snap;
    const auto collect = [levels](const PriceLadder& side, std::vector<DepthLevel>& out) {
        for (std::size_t i = 0; i < side.depth() && out.size() < levels; ++i) {
            const PriceLevel& level = side.level_from_best(i);
            if (is_market_price(level.price)) continue;  // auction market orders are not depth
            out.push_back({level.price, level.visible, level.count});
        }
    };
    collect(bids_, snap.bids);
    collect(asks_, snap.asks);
    return snap;
}

std::optional<RestingOrder> OrderBook::find(OrderId id) const {
    const auto it = index_.find(id);
    if (it == index_.end()) return std::nullopt;
    const OrderNode& n = pool_[it->second];
    return RestingOrder{n.id, n.owner, n.side, n.price, n.visible, n.hidden, n.priority};
}

std::optional<UncrossResult> OrderBook::indicative_uncross() const {
    if (phase_ != Phase::Auction) return std::nullopt;
    std::vector<AuctionInterest> buy;
    std::vector<AuctionInterest> sell;
    for (std::size_t i = 0; i < bids_.depth(); ++i) {
        const auto& l = bids_.level_from_best(i);
        buy.push_back({l.price, l.visible + l.hidden});
    }
    for (std::size_t i = 0; i < asks_.depth(); ++i) {
        const auto& l = asks_.level_from_best(i);
        sell.push_back({l.price, l.visible + l.hidden});
    }
    return compute_uncross(buy, sell, reference_);
}

std::uint64_t OrderBook::state_hash() const noexcept {
    std::uint64_t h = kFnvOffset;
    fnv_mix(h, static_cast<std::uint64_t>(phase_));
    fnv_mix(h, static_cast<std::uint64_t>(reference_));
    for (const PriceLadder* side : {&bids_, &asks_}) {
        fnv_mix(h, side->depth());
        for (std::size_t i = 0; i < side->depth(); ++i) {
            const PriceLevel& level = side->level_from_best(i);
            for (NodeIndex idx = level.head; idx != kNullNode; idx = pool_[idx].next) {
                const OrderNode& n = pool_[idx];
                fnv_mix(h, n.id);
                fnv_mix(h, n.owner);
                fnv_mix(h, static_cast<std::uint64_t>(n.price));
                fnv_mix(h, static_cast<std::uint64_t>(n.visible));
                fnv_mix(h, static_cast<std::uint64_t>(n.hidden));
            }
        }
    }
    return h;
}

std::string OrderBook::check_invariants() const {
    std::ostringstream err;
    std::size_t nodes = 0;
    for (const PriceLadder* side : {&bids_, &asks_}) {
        for (std::size_t i = 0; i < side->depth(); ++i) {
            const PriceLevel& level = side->level_from_best(i);
            if (i + 1 < side->depth() &&
                !side->better(level.price, side->level_from_best(i + 1).price)) {
                err << "levels out of order at " << level.price << "; ";
            }
            Qty visible = 0;
            Qty hidden = 0;
            std::uint32_t count = 0;
            NodeIndex prev = kNullNode;
            Seq last_priority = 0;
            for (NodeIndex idx = level.head; idx != kNullNode; idx = pool_[idx].next) {
                const OrderNode& n = pool_[idx];
                if (n.prev != prev) err << "broken prev link at #" << n.id << "; ";
                if (n.price != level.price) err << "order #" << n.id << " on wrong level; ";
                if (n.side != side->side()) err << "order #" << n.id << " on wrong side; ";
                if (n.priority <= last_priority) err << "time priority broken at #" << n.id << "; ";
                if (n.visible <= 0 && n.hidden <= 0) err << "empty order #" << n.id << "; ";
                if (n.visible < 0 || n.hidden < 0) err << "negative qty #" << n.id << "; ";
                const auto it = index_.find(n.id);
                if (it == index_.end() || it->second != idx) err << "index miss #" << n.id << "; ";
                last_priority = n.priority;
                visible += n.visible;
                hidden += n.hidden;
                ++count;
                prev = idx;
            }
            if (level.tail != prev) err << "tail mismatch at " << level.price << "; ";
            if (count != level.count || count == 0)
                err << "count mismatch at " << level.price << "; ";
            if (visible != level.visible)
                err << "visible total mismatch at " << level.price << "; ";
            if (hidden != level.hidden) err << "hidden total mismatch at " << level.price << "; ";
            nodes += count;
        }
    }
    if (nodes != index_.size())
        err << "index size " << index_.size() << " != nodes " << nodes << "; ";
    if (nodes != pool_.live()) err << "pool live " << pool_.live() << " != nodes " << nodes << "; ";
    if (phase_ == Phase::Continuous && !bids_.empty() && !asks_.empty() &&
        bids_.best().price >= asks_.best().price) {
        err << "book crossed in continuous trading; ";
    }
    return err.str();
}

// ---- helpers --------------------------------------------------------------------------------

bool OrderBook::crosses(Side side, Price limit, Price resting) const noexcept {
    return side == Side::Buy ? limit >= resting : limit <= resting;
}

bool OrderBook::inside_collar(Price p) const noexcept {
    if (config_.collar_bps <= 0 || collar_ref_ <= 0) return true;
    const Price diff = p > collar_ref_ ? p - collar_ref_ : collar_ref_ - p;
    // Compare diff / reference <= bps / 10000 without dividing.
    return diff * 10'000 <= config_.collar_bps * collar_ref_;
}

std::optional<RejectReason> OrderBook::validate(const NewOrder& o) const {
    if (phase_ == Phase::Halted) return RejectReason::MarketHalted;
    if (o.qty <= 0) return RejectReason::InvalidQuantity;
    if (index_.contains(o.id)) return RejectReason::DuplicateOrderId;
    if (o.type == OrderType::Market) {
        if (o.post_only) return RejectReason::InvalidPrice;
    } else {
        if (o.price <= 0) return RejectReason::InvalidPrice;
        if (!config_.ticks.is_valid(o.price)) return RejectReason::TickSizeViolation;
    }
    if (o.type == OrderType::Iceberg) {
        if (o.display_qty <= 0 || o.display_qty > o.qty) {
            return RejectReason::InvalidDisplayQuantity;
        }
    } else if (o.display_qty != 0) {
        return RejectReason::InvalidDisplayQuantity;
    }
    if (phase_ == Phase::Auction && o.tif != TimeInForce::Day) {
        return RejectReason::NotPermittedInPhase;
    }
    return std::nullopt;
}

Qty OrderBook::fillable(const NewOrder& o, Price limit, Qty wanted) const {
    const PriceLadder& opp = ladder(opposite(o.side));
    Qty available = 0;
    for (std::size_t i = 0; i < opp.depth() && available < wanted; ++i) {
        const PriceLevel& level = opp.level_from_best(i);
        if (!crosses(o.side, limit, level.price) || !inside_collar(level.price)) break;
        for (NodeIndex idx = level.head; idx != kNullNode && available < wanted;
             idx = pool_[idx].next) {
            const OrderNode& n = pool_[idx];
            if (n.owner == o.owner && o.stp != StpMode::None) {
                // CancelResting skips our own order; the other modes would kill the incoming
                // order here, so nothing beyond this point can count.
                if (o.stp == StpMode::CancelResting) continue;
                return available;
            }
            available += n.total();
        }
    }
    return std::min(available, wanted);
}

void OrderBook::emit_trade(const OrderNode& resting, OrderId incoming, ParticipantId incoming_owner,
                           Side aggressor, Price price, Qty qty, bool auction) {
    const bool resting_is_buy = resting.side == Side::Buy;
    events_.emplace_back(Trade{
        next_trade_++, resting_is_buy ? resting.id : incoming,
        resting_is_buy ? incoming : resting.id, resting_is_buy ? resting.owner : incoming_owner,
        resting_is_buy ? incoming_owner : resting.owner, aggressor, price, qty, auction});
    reference_ = price;
}

void OrderBook::enter_auction(Price trigger) {
    const Phase from = phase_;
    phase_ = Phase::Auction;
    events_.emplace_back(PhaseChanged{from, Phase::Auction, trigger});
}

void OrderBook::rest(const NewOrder& o, Price price, Qty qty, bool is_market) {
    const NodeIndex idx = pool_.allocate();
    OrderNode& n = pool_[idx];
    n.id = o.id;
    n.owner = o.owner;
    n.side = o.side;
    n.stp = o.stp;
    n.is_market = is_market;
    n.price = price;
    if (o.type == OrderType::Iceberg) {
        n.peak = std::min(o.display_qty, qty);
        n.visible = n.peak;
        n.hidden = qty - n.visible;
    } else {
        n.visible = qty;
    }
    n.priority = next_priority_++;
    ladder(o.side).push_back(pool_, idx);
    index_.emplace(o.id, idx);
    ++open_by_owner_[o.owner];
}

void OrderBook::remove_resting(NodeIndex idx) {
    const OrderNode& n = pool_[idx];
    const OrderId id = n.id;
    const ParticipantId owner = n.owner;
    ladder(n.side).unlink(pool_, idx);
    index_.erase(id);
    if (auto it = open_by_owner_.find(owner); it != open_by_owner_.end() && --it->second == 0) {
        open_by_owner_.erase(it);
    }
    pool_.release(idx);
}

Qty OrderBook::match(const NewOrder& o, Price limit, Qty qty, bool& incoming_killed) {
    PriceLadder& opp = ladder(opposite(o.side));
    // One resting order per iteration, always from the head of the best level. Re-reading the
    // best level each time keeps us safe when a level is erased mid-match.
    while (qty > 0 && !opp.empty()) {
        PriceLevel& level = opp.best();
        if (!crosses(o.side, limit, level.price)) break;
        if (!inside_collar(level.price)) {
            enter_auction(level.price);
            break;
        }
        const NodeIndex idx = level.head;
        OrderNode& resting = pool_[idx];

        if (resting.owner == o.owner && o.stp != StpMode::None) {
            if (o.stp == StpMode::CancelResting || o.stp == StpMode::CancelBoth) {
                events_.emplace_back(
                    Cancelled{resting.id, resting.total(), CancelReason::SelfTradePrevention});
                remove_resting(idx);
            }
            if (o.stp == StpMode::CancelIncoming || o.stp == StpMode::CancelBoth) {
                events_.emplace_back(Cancelled{o.id, qty, CancelReason::SelfTradePrevention});
                incoming_killed = true;
                return 0;
            }
            continue;
        }

        const Qty fill = std::min(qty, resting.visible);
        emit_trade(resting, o.id, o.owner, o.side, level.price, fill, false);
        resting.visible -= fill;
        level.visible -= fill;
        qty -= fill;

        if (resting.visible == 0) {
            if (resting.hidden > 0) {
                // Iceberg refresh: show a new peak and go to the back of the queue.
                const Qty refresh = std::min(resting.peak, resting.hidden);
                resting.hidden -= refresh;
                resting.visible = refresh;
                level.hidden -= refresh;
                level.visible += refresh;
                resting.priority = next_priority_++;
                opp.move_to_back(pool_, idx);
            } else {
                remove_resting(idx);
            }
        }
    }
    return qty;
}

// ---- commands -------------------------------------------------------------------------------

const std::vector<Event>& OrderBook::submit(const NewOrder& o) {
    begin();
    if (const auto reason = validate(o)) {
        events_.emplace_back(Rejected{o.id, *reason});
        return events_;
    }
    const bool is_market = o.type == OrderType::Market;
    const Price limit =
        is_market ? (o.side == Side::Buy ? kMarketBuyPrice : kMarketSellPrice) : o.price;

    if (phase_ == Phase::Auction) {
        events_.emplace_back(Accepted{o.id});
        rest(o, limit, o.qty, is_market);
        return events_;
    }

    const PriceLadder& opp = ladder(opposite(o.side));
    if (o.post_only && !opp.empty() && crosses(o.side, limit, opp.best().price)) {
        events_.emplace_back(Rejected{o.id, RejectReason::PostOnlyWouldCross});
        return events_;
    }
    if (o.tif == TimeInForce::FOK && fillable(o, limit, o.qty) < o.qty) {
        events_.emplace_back(Rejected{o.id, RejectReason::FokNotFillable});
        return events_;
    }

    events_.emplace_back(Accepted{o.id});
    bool killed = false;
    const Qty remainder = match(o, limit, o.qty, killed);
    if (remainder > 0 && !killed) {
        if (o.tif != TimeInForce::Day) {
            events_.emplace_back(Cancelled{o.id, remainder, CancelReason::ImmediateRemainder});
        } else if (phase_ == Phase::Auction) {
            // The collar tripped mid-match: a day order (market or limit) joins the volatility
            // auction instead of being thrown away.
            rest(o, limit, remainder, is_market);
        } else if (is_market) {
            events_.emplace_back(Cancelled{o.id, remainder, CancelReason::ImmediateRemainder});
        } else {
            rest(o, limit, remainder, false);
        }
    }
    return events_;
}

const std::vector<Event>& OrderBook::cancel(const CancelOrder& request) {
    begin();
    const auto it = index_.find(request.id);
    if (it == index_.end()) {
        events_.emplace_back(Rejected{request.id, RejectReason::UnknownOrder});
        return events_;
    }
    const NodeIndex idx = it->second;
    events_.emplace_back(Cancelled{request.id, pool_[idx].total(), CancelReason::UserRequested});
    remove_resting(idx);
    return events_;
}

const std::vector<Event>& OrderBook::amend(const AmendOrder& request) {
    begin();
    const auto it = index_.find(request.id);
    if (it == index_.end()) {
        events_.emplace_back(Rejected{request.id, RejectReason::UnknownOrder});
        return events_;
    }
    if (phase_ == Phase::Halted) {
        events_.emplace_back(Rejected{request.id, RejectReason::MarketHalted});
        return events_;
    }
    const NodeIndex idx = it->second;
    OrderNode& n = pool_[idx];
    if (request.new_qty <= 0) {
        events_.emplace_back(Rejected{request.id, RejectReason::InvalidQuantity});
        return events_;
    }
    if (n.is_market || request.new_price <= 0) {
        events_.emplace_back(Rejected{request.id, RejectReason::InvalidPrice});
        return events_;
    }
    if (!config_.ticks.is_valid(request.new_price)) {
        events_.emplace_back(Rejected{request.id, RejectReason::TickSizeViolation});
        return events_;
    }

    if (request.new_price == n.price && request.new_qty <= n.total()) {
        // Size-down in place keeps the queue position.
        PriceLevel* level = ladder(n.side).find(n.price);
        const Qty new_visible = std::min(n.visible, request.new_qty);
        const Qty new_hidden = request.new_qty - new_visible;
        level->visible += new_visible - n.visible;
        level->hidden += new_hidden - n.hidden;
        n.visible = new_visible;
        n.hidden = new_hidden;
        events_.emplace_back(Amended{n.id, n.price, request.new_qty, true});
        return events_;
    }

    // Anything else is cancel-replace: same id, back of the queue, and it may trade.
    NewOrder replacement;
    replacement.id = n.id;
    replacement.owner = n.owner;
    replacement.side = n.side;
    replacement.stp = n.stp;
    replacement.price = request.new_price;
    replacement.qty = request.new_qty;
    if (n.peak > 0) {
        replacement.type = OrderType::Iceberg;
        replacement.display_qty = std::min(n.peak, request.new_qty);
    }
    remove_resting(idx);
    events_.emplace_back(Amended{replacement.id, replacement.price, replacement.qty, false});
    if (phase_ == Phase::Auction) {
        rest(replacement, replacement.price, replacement.qty, false);
        return events_;
    }
    bool killed = false;
    const Qty remainder = match(replacement, replacement.price, replacement.qty, killed);
    if (remainder > 0 && !killed) rest(replacement, replacement.price, remainder, false);
    return events_;
}

const std::vector<Event>& OrderBook::start_auction() {
    begin();
    if (phase_ == Phase::Continuous) enter_auction(reference_);
    return events_;
}

const std::vector<Event>& OrderBook::halt() {
    begin();
    if (phase_ != Phase::Halted) {
        events_.emplace_back(PhaseChanged{phase_, Phase::Halted, reference_});
        phase_ = Phase::Halted;
    }
    return events_;
}

const std::vector<Event>& OrderBook::resume() {
    begin();
    // A halted market re-opens through an auction so the first price is discovered fairly.
    if (phase_ == Phase::Halted) {
        events_.emplace_back(PhaseChanged{Phase::Halted, Phase::Auction, reference_});
        phase_ = Phase::Auction;
    }
    return events_;
}

const std::vector<Event>& OrderBook::uncross() {
    begin();
    if (phase_ != Phase::Auction) return events_;

    const auto result = indicative_uncross();
    if (result) {
        const Price price = result->price;
        Qty volume = result->volume;
        // Take one share from both sides in price-time priority until the volume is done.
        const auto consume = [this](PriceLadder& side, NodeIndex idx, Qty qty) {
            OrderNode& n = pool_[idx];
            const Qty left = n.total() - qty;
            if (left == 0) {
                // Zero the totals first so unlink() does not subtract them twice.
                PriceLevel* level = side.find(n.price);
                level->visible -= n.visible;
                level->hidden -= n.hidden;
                n.visible = 0;
                n.hidden = 0;
                remove_resting(idx);
                return;
            }
            const Qty visible = n.peak > 0 ? std::min(n.peak, left) : left;
            PriceLevel* level = side.find(n.price);
            level->visible += visible - n.visible;
            level->hidden += (left - visible) - n.hidden;
            n.visible = visible;
            n.hidden = left - visible;
        };
        while (volume > 0) {
            const NodeIndex b = bids_.best().head;
            const NodeIndex s = asks_.best().head;
            const Qty fill = std::min({volume, pool_[b].total(), pool_[s].total()});
            emit_trade(pool_[b], pool_[s].id, pool_[s].owner, Side::Buy, price, fill, true);
            consume(bids_, b, fill);
            consume(asks_, s, fill);
            volume -= fill;
        }
    }

    // Market orders cannot rest in continuous trading.
    for (PriceLadder* side : {&bids_, &asks_}) {
        while (!side->empty() && is_market_price(side->best().price)) {
            const NodeIndex idx = side->best().head;
            events_.emplace_back(
                Cancelled{pool_[idx].id, pool_[idx].total(), CancelReason::AuctionRemainder});
            remove_resting(idx);
        }
    }
    events_.emplace_back(
        PhaseChanged{Phase::Auction, Phase::Continuous, result ? result->price : reference_});
    phase_ = Phase::Continuous;
    return events_;
}

}  // namespace lob
