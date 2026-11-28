#pragma once

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <variant>
#include <vector>

#include "lob/order_book.hpp"

namespace lob::test {

inline BookConfig test_config(std::int64_t collar_bps = 0, Price reference = 100'000) {
    BookConfig cfg;
    cfg.symbol = "TGX";
    cfg.collar_bps = collar_bps;
    cfg.reference_price = reference;  // 1000.00p: tick is 0.5p (50 units) from here to 5000p
    cfg.expected_orders = 64;
    return cfg;
}

inline NewOrder limit(OrderId id, Side side, Price price, Qty qty, ParticipantId owner = 0) {
    NewOrder o;
    o.id = id;
    o.owner = owner == 0 ? static_cast<ParticipantId>(id) : owner;
    o.side = side;
    o.price = price;
    o.qty = qty;
    return o;
}

inline NewOrder market(OrderId id, Side side, Qty qty, ParticipantId owner = 0) {
    NewOrder o = limit(id, side, 0, qty, owner);
    o.type = OrderType::Market;
    return o;
}

inline NewOrder iceberg(OrderId id, Side side, Price price, Qty qty, Qty peak,
                        ParticipantId owner = 0) {
    NewOrder o = limit(id, side, price, qty, owner);
    o.type = OrderType::Iceberg;
    o.display_qty = peak;
    return o;
}

template <class T>
std::vector<T> only(const std::vector<Event>& events) {
    std::vector<T> out;
    for (const auto& e : events) {
        if (const auto* x = std::get_if<T>(&e)) out.push_back(*x);
    }
    return out;
}

inline Qty traded(const std::vector<Event>& events) {
    Qty q = 0;
    for (const auto& t : only<Trade>(events)) q += t.qty;
    return q;
}

#define EXPECT_BOOK_OK(book) EXPECT_EQ((book).check_invariants(), std::string{})

}  // namespace lob::test
