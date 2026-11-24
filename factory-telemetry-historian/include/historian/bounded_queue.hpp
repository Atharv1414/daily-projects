#pragma once

#include <condition_variable>
#include <cstddef>
#include <deque>
#include <mutex>
#include <optional>
#include <utility>

namespace historian {

/// Blocking multi-producer, multi-consumer queue. Closing wakes everyone; consumers drain
/// what is left.
template <typename T>
class BoundedQueue {
  public:
    explicit BoundedQueue(std::size_t capacity) : capacity_(capacity) {}

    /// Returns false if the queue is closed.
    [[nodiscard]] bool push(T item) {
        std::unique_lock lock(mutex_);
        not_full_.wait(lock, [&] { return closed_ || items_.size() < capacity_; });
        if (closed_) {
            return false;
        }
        items_.push_back(std::move(item));
        lock.unlock();
        not_empty_.notify_one();
        return true;
    }

    /// Returns nullopt once the queue is closed and empty.
    [[nodiscard]] std::optional<T> pop() {
        std::unique_lock lock(mutex_);
        not_empty_.wait(lock, [&] { return closed_ || !items_.empty(); });
        if (items_.empty()) {
            return std::nullopt;
        }
        std::optional<T> item(std::move(items_.front()));
        items_.pop_front();
        lock.unlock();
        not_full_.notify_one();
        return item;
    }

    void close() {
        {
            const std::lock_guard lock(mutex_);
            closed_ = true;
        }
        not_full_.notify_all();
        not_empty_.notify_all();
    }

  private:
    std::size_t capacity_;
    std::mutex mutex_;
    std::condition_variable not_full_;
    std::condition_variable not_empty_;
    std::deque<T> items_;
    bool closed_ = false;
};

}  // namespace historian
