#pragma once

#include <cstdint>
#include <vector>

#include "jobsearch/types.hpp"

namespace jobsearch {

/// SplitMix64. Used instead of <random> distributions because those are allowed to differ
/// between standard libraries, and the corpus must be identical on GCC, Clang and Apple clang.
class Rng {
  public:
    explicit Rng(std::uint64_t seed) noexcept : state_(seed) {}
    [[nodiscard]] std::uint64_t next() noexcept;
    /// Uniform in [0, n). n must be > 0.
    [[nodiscard]] std::uint64_t below(std::uint64_t n) noexcept { return next() % n; }
    [[nodiscard]] double unit() noexcept;  // [0, 1)
    [[nodiscard]] bool chance(double p) noexcept { return unit() < p; }

  private:
    std::uint64_t state_;
};

struct CorpusOptions {
    std::size_t jobs = 10'000;
    std::uint64_t seed = 42;
    std::uint32_t days = 90;    // posting window
    double repost_rate = 0.04;  // agencies re-posting the same advert under a new id
};

/// Generates realistic UK job adverts: 14 job families, seniority levels, regional salary
/// weighting (London pays more), agency re-posts, remote roles and skill lists.
[[nodiscard]] std::vector<JobAd> generate_corpus(const CorpusOptions& options);

}  // namespace jobsearch
