#pragma once

#include <atomic>
#include <bit>
#include <cstddef>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

namespace lob {

/// Bounded single-producer / single-consumer queue.
///
/// One thread may call try_push, one (other) thread may call try_pop. The producer owns `head_`
/// and the consumer owns `tail_`; each reads the other's index with acquire and publishes its
/// own with release, so a slot's contents are visible before its index moves. Each side also
/// caches the other's index to avoid touching the shared cache line on every call.
template <class T>
class SpscRing {
  public:
    explicit SpscRing(std::size_t capacity) {
        if (capacity < 2 || !std::has_single_bit(capacity)) {
            throw std::invalid_argument("SpscRing capacity must be a power of two >= 2");
        }
        slots_.resize(capacity);
        mask_ = capacity - 1;
    }

    SpscRing(const SpscRing&) = delete;
    SpscRing& operator=(const SpscRing&) = delete;

    [[nodiscard]] bool try_push(T value) {
        const std::size_t head = head_.load(std::memory_order_relaxed);
        if (head - cached_tail_ == slots_.size()) {
            cached_tail_ = tail_.load(std::memory_order_acquire);
            if (head - cached_tail_ == slots_.size()) return false;  // full
        }
        slots_[head & mask_] = std::move(value);
        head_.store(head + 1, std::memory_order_release);
        return true;
    }

    [[nodiscard]] std::optional<T> try_pop() {
        const std::size_t tail = tail_.load(std::memory_order_relaxed);
        if (tail == cached_head_) {
            cached_head_ = head_.load(std::memory_order_acquire);
            if (tail == cached_head_) return std::nullopt;  // empty
        }
        std::optional<T> out(std::move(slots_[tail & mask_]));
        tail_.store(tail + 1, std::memory_order_release);
        return out;
    }

    [[nodiscard]] std::size_t capacity() const noexcept { return slots_.size(); }
    /// Approximate (racy) size, for monitoring only.
    [[nodiscard]] std::size_t size_approx() const noexcept {
        return head_.load(std::memory_order_acquire) - tail_.load(std::memory_order_acquire);
    }

  private:
    std::vector<T> slots_;
    std::size_t mask_ = 0;
    alignas(64) std::atomic<std::size_t> head_{0};
    std::size_t cached_tail_ = 0;  // producer-local
    alignas(64) std::atomic<std::size_t> tail_{0};
    std::size_t cached_head_ = 0;  // consumer-local
};

}  // namespace lob
