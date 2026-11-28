#include "lob/order_flow.hpp"

#include <algorithm>
#include <cmath>
#include <utility>

namespace lob {

std::int64_t SplitMix64::between(std::int64_t lo, std::int64_t hi) noexcept {
    const auto span = static_cast<std::uint64_t>(hi - lo) + 1u;
    return lo + static_cast<std::int64_t>(next() % span);
}

double SplitMix64::unit() noexcept {
    return static_cast<double>(next() >> 11) * (1.0 / 9007199254740992.0);  // 2^53
}

OrderFlowGenerator::OrderFlowGenerator(FlowProfile profile, std::uint64_t seed)
    : profile_(std::move(profile)),
      ticks_(TickTable::uk_liquid()),
      rng_(seed),
      mid_(static_cast<double>(profile_.start_mid)) {
    live_.reserve(1 << 16);
}

OrderId OrderFlowGenerator::pick_live() {
    const auto i =
        static_cast<std::size_t>(rng_.between(0, static_cast<std::int64_t>(live_.size()) - 1));
    return live_[i];
}

void OrderFlowGenerator::add_live(OrderId id, Qty qty) {
    info_[id] = LiveOrder{live_.size(), qty};
    live_.push_back(id);
}

void OrderFlowGenerator::drop_live(OrderId id) {
    const auto it = info_.find(id);
    if (it == info_.end()) return;
    const std::size_t pos = it->second.pos;
    const OrderId moved = live_.back();
    live_[pos] = moved;
    info_[moved].pos = pos;
    live_.pop_back();
    info_.erase(id);
}

void OrderFlowGenerator::observe(std::span<const Event> events) {
    for (const Event& e : events) {
        if (const auto* t = std::get_if<Trade>(&e)) {
            for (const OrderId id : {t->buy_id, t->sell_id}) {
                const auto it = info_.find(id);
                if (it != info_.end() && (it->second.remaining -= t->qty) <= 0) drop_live(id);
            }
        } else if (const auto* c = std::get_if<Cancelled>(&e)) {
            drop_live(c->id);
        } else if (const auto* r = std::get_if<Rejected>(&e)) {
            drop_live(r->id);
        } else if (const auto* a = std::get_if<Amended>(&e)) {
            if (auto it = info_.find(a->id); it != info_.end()) it->second.remaining = a->qty;
        }
    }
}

std::vector<Command> generate_session(const FlowProfile& profile, std::uint64_t seed, std::size_t n,
                                      const BookConfig& book) {
    OrderFlowGenerator gen(profile, seed);
    OrderBook scratch(book);
    std::vector<Command> out;
    out.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        Command c = gen.next();
        const std::vector<Event>* events = nullptr;
        if (const auto* s = std::get_if<SubmitCmd>(&c)) {
            events = &scratch.submit(s->order);
        } else if (const auto* x = std::get_if<CancelCmd>(&c)) {
            events = &scratch.cancel(x->request);
        } else if (const auto* a = std::get_if<AmendCmd>(&c)) {
            events = &scratch.amend(a->request);
        }
        if (events != nullptr) gen.observe(*events);
        out.push_back(std::move(c));
    }
    return out;
}

Command OrderFlowGenerator::next() {
    // The mid drifts like a slow random walk, a fraction of a tick per message.
    const auto tick = static_cast<double>(ticks_.tick_for(static_cast<Price>(mid_)));
    mid_ += (rng_.unit() - 0.5) * tick * 0.3;

    const auto roll = static_cast<int>(rng_.between(0, 99));
    if (roll < profile_.pct_cancel && !live_.empty()) {
        const OrderId id = pick_live();
        drop_live(id);
        return CancelCmd{profile_.symbol, CancelOrder{id}};
    }
    if (roll < profile_.pct_cancel + profile_.pct_amend && !live_.empty()) {
        // Amends re-price an order close to the current mid. Without feedback (observe) some
        // ids will be stale, which exercises the reject path.
        const OrderId id = pick_live();
        const auto offset = static_cast<Price>(rng_.between(1, 10)) * static_cast<Price>(tick);
        const bool buy = (id & 1u) == 0;  // generator convention: even ids are bids
        const Price price = ticks_.round_down(static_cast<Price>(mid_) + (buy ? -offset : offset));
        return AmendCmd{profile_.symbol, AmendOrder{id, price, rng_.between(1, 20) * 100}};
    }
    return new_order();
}

Command OrderFlowGenerator::new_order() {
    SubmitCmd cmd;
    cmd.symbol = profile_.symbol;
    NewOrder& o = cmd.order;
    o.id = next_id_++;
    o.owner = static_cast<ParticipantId>(rng_.between(1, profile_.participants));
    o.side = (o.id & 1u) == 0 ? Side::Buy : Side::Sell;
    o.stp = StpMode::CancelResting;
    o.qty = rng_.between(1, 20) * 100;
    if (rng_.unit() < 0.03) o.qty *= 10;  // the occasional block

    const auto tick = ticks_.tick_for(static_cast<Price>(mid_));
    const bool buy = o.side == Side::Buy;
    const auto roll = static_cast<int>(rng_.between(0, 99));
    int band = profile_.pct_marketable;

    if (roll < band) {
        if (rng_.unit() < 0.4) {
            o.type = OrderType::Market;
            o.tif = TimeInForce::IOC;
        } else {
            o.tif = TimeInForce::IOC;
            const Price through = static_cast<Price>(rng_.between(1, 4)) * tick;
            o.price = ticks_.round_down(static_cast<Price>(mid_) + (buy ? through : -through));
        }
        return cmd;
    }
    band += profile_.pct_fok;
    if (roll < band) {
        o.tif = TimeInForce::FOK;
        const Price through = static_cast<Price>(rng_.between(1, 3)) * tick;
        o.price = ticks_.round_down(static_cast<Price>(mid_) + (buy ? through : -through));
        return cmd;
    }

    // Passive interest, skewed towards the touch: offset = max_ticks * u^2.
    const double u = rng_.unit();
    const auto offset_ticks =
        static_cast<Price>(std::floor(u * u * static_cast<double>(profile_.max_ticks_from_mid))) +
        1;
    const Price base = static_cast<Price>(mid_);
    o.price = ticks_.round_down(buy ? base - offset_ticks * tick : base + offset_ticks * tick);
    if (!buy) o.price += tick;  // keep asks strictly above bids at the same offset

    band += profile_.pct_iceberg;
    if (roll < band) {
        o.type = OrderType::Iceberg;
        o.qty = rng_.between(20, 100) * 100;
        o.display_qty = rng_.between(2, 5) * 100;
    } else if (roll < band + profile_.pct_post_only) {
        o.post_only = true;
    }
    add_live(o.id, o.qty);
    return cmd;
}

}  // namespace lob
