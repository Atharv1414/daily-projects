#include "lob/price_ladder.hpp"

#include <algorithm>
#include <cstddef>
#include <iterator>

namespace lob {

std::size_t PriceLadder::position(Price price) const noexcept {
    // levels_ runs worst -> best, so a level is "less" than `price` when it is worse.
    const auto it = std::lower_bound(
        levels_.begin(), levels_.end(), price,
        [this](const PriceLevel& level, Price p) { return better(p, level.price); });
    return static_cast<std::size_t>(std::distance(levels_.begin(), it));
}

PriceLevel* PriceLadder::find(Price price) noexcept {
    const std::size_t pos = position(price);
    if (pos < levels_.size() && levels_[pos].price == price) return &levels_[pos];
    return nullptr;
}

void PriceLadder::push_back(OrderPool& pool, NodeIndex idx) {
    OrderNode& node = pool[idx];
    const std::size_t pos = position(node.price);
    if (pos == levels_.size() || levels_[pos].price != node.price) {
        PriceLevel fresh;
        fresh.price = node.price;
        levels_.insert(levels_.begin() + static_cast<std::ptrdiff_t>(pos), fresh);
    }
    PriceLevel& level = levels_[pos];
    node.prev = level.tail;
    node.next = kNullNode;
    if (level.tail != kNullNode) {
        pool[level.tail].next = idx;
    } else {
        level.head = idx;
    }
    level.tail = idx;
    level.visible += node.visible;
    level.hidden += node.hidden;
    ++level.count;
}

void PriceLadder::unlink(OrderPool& pool, NodeIndex idx) {
    OrderNode& node = pool[idx];
    const std::size_t pos = position(node.price);
    PriceLevel& level = levels_[pos];
    if (node.prev != kNullNode) {
        pool[node.prev].next = node.next;
    } else {
        level.head = node.next;
    }
    if (node.next != kNullNode) {
        pool[node.next].prev = node.prev;
    } else {
        level.tail = node.prev;
    }
    level.visible -= node.visible;
    level.hidden -= node.hidden;
    --level.count;
    node.prev = node.next = kNullNode;
    if (level.count == 0) levels_.erase(levels_.begin() + static_cast<std::ptrdiff_t>(pos));
}

void PriceLadder::move_to_back(OrderPool& pool, NodeIndex idx) {
    PriceLevel* level = find(pool[idx].price);
    if (level == nullptr || level->tail == idx) return;
    OrderNode& node = pool[idx];
    // Detach without touching the totals.
    if (node.prev != kNullNode) {
        pool[node.prev].next = node.next;
    } else {
        level->head = node.next;
    }
    pool[node.next].prev = node.prev;  // node.next exists because idx is not the tail
    // Re-attach at the tail.
    node.prev = level->tail;
    node.next = kNullNode;
    pool[level->tail].next = idx;
    level->tail = idx;
}

Qty PriceLadder::total_visible() const noexcept {
    Qty total = 0;
    for (const auto& level : levels_) total += level.visible;
    return total;
}

}  // namespace lob
