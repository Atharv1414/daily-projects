#pragma once

#include <cstddef>
#include <functional>
#include <map>
#include <string>
#include <string_view>
#include <vector>

#include "historian/types.hpp"

namespace historian {

/// Recent samples, sorted per series. A repeated timestamp overwrites (last write wins).
class Memtable {
  public:
    using SeriesMap = std::map<std::string, std::vector<Sample>, std::less<>>;

    void insert(std::string_view series, Sample sample);
    /// Samples with from <= ts < to.
    [[nodiscard]] std::vector<Sample> range(std::string_view series, TimestampMs from,
                                            TimestampMs to) const;
    [[nodiscard]] const SeriesMap& series() const noexcept { return series_; }
    [[nodiscard]] std::size_t size() const noexcept { return size_; }
    [[nodiscard]] std::size_t late_inserts() const noexcept { return late_; }
    [[nodiscard]] std::size_t overwrites() const noexcept { return overwrites_; }
    void clear();

  private:
    SeriesMap series_;
    std::size_t size_ = 0;
    std::size_t late_ = 0;
    std::size_t overwrites_ = 0;
};

}  // namespace historian
