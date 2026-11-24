#include "historian/memtable.hpp"

#include <algorithm>

namespace historian {

void Memtable::insert(std::string_view series, Sample sample) {
    auto it = series_.find(series);
    if (it == series_.end()) {
        it = series_.emplace(std::string(series), std::vector<Sample>{}).first;
    }
    auto& samples = it->second;
    if (samples.empty() || samples.back().ts < sample.ts) {  // in-order fast path
        samples.push_back(sample);
        ++size_;
        return;
    }
    const auto pos = std::ranges::lower_bound(samples, sample.ts, {}, &Sample::ts);
    if (pos->ts == sample.ts) {
        pos->value = sample.value;
        ++overwrites_;
        return;
    }
    samples.insert(pos, sample);
    ++size_;
    ++late_;
}

std::vector<Sample> Memtable::range(std::string_view series, TimestampMs from,
                                    TimestampMs to) const {
    const auto it = series_.find(series);
    if (it == series_.end() || from >= to) {
        return {};
    }
    const auto first = std::ranges::lower_bound(it->second, from, {}, &Sample::ts);
    const auto last = std::ranges::lower_bound(it->second, to, {}, &Sample::ts);
    return {first, last};
}

void Memtable::clear() {
    series_.clear();
    size_ = 0;
    late_ = 0;
    overwrites_ = 0;
}

}  // namespace historian
