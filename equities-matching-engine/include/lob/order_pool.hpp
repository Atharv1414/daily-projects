#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "lob/types.hpp"

namespace lob {

/// Index into the pool. Using 32-bit indices rather than pointers halves the size of the links
/// and keeps nodes valid when the pool grows.
using NodeIndex = std::uint32_t;
inline constexpr NodeIndex kNullNode = 0xFFFF'FFFFu;

/// A resting order. Nodes form an intrusive doubly linked FIFO per price level.
struct OrderNode {
    OrderId id = 0;
    ParticipantId owner = 0;
    Side side = Side::Buy;
    StpMode stp = StpMode::None;
    bool is_market = false;  ///< only during an auction call phase
    Price price = 0;
    Qty visible = 0;   ///< quantity shown on the book
    Qty hidden = 0;    ///< iceberg reserve
    Qty peak = 0;      ///< iceberg display size (0 = not an iceberg)
    Seq priority = 0;  ///< lower = earlier
    NodeIndex prev = kNullNode;
    NodeIndex next = kNullNode;

    [[nodiscard]] Qty total() const noexcept { return visible + hidden; }
};
static_assert(sizeof(OrderNode) == 64, "an order node should fill exactly one cache line");

/// Free-list allocator for order nodes. After warm-up, adding and removing orders allocates
/// nothing, which keeps latency flat.
class OrderPool {
  public:
    explicit OrderPool(std::size_t reserve = 0) {
        nodes_.reserve(reserve);
        free_.reserve(reserve);
    }

    [[nodiscard]] NodeIndex allocate() {
        if (!free_.empty()) {
            const NodeIndex idx = free_.back();
            free_.pop_back();
            nodes_[idx] = OrderNode{};
            ++live_;
            return idx;
        }
        nodes_.emplace_back();
        ++live_;
        return static_cast<NodeIndex>(nodes_.size() - 1);
    }

    void release(NodeIndex idx) {
        free_.push_back(idx);
        --live_;
    }

    [[nodiscard]] OrderNode& operator[](NodeIndex idx) noexcept { return nodes_[idx]; }
    [[nodiscard]] const OrderNode& operator[](NodeIndex idx) const noexcept { return nodes_[idx]; }
    [[nodiscard]] std::size_t live() const noexcept { return live_; }
    [[nodiscard]] std::size_t capacity() const noexcept { return nodes_.size(); }

  private:
    std::vector<OrderNode> nodes_;
    std::vector<NodeIndex> free_;
    std::size_t live_ = 0;
};

}  // namespace lob
