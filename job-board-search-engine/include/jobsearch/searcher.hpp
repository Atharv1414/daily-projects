#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "jobsearch/index.hpp"
#include "jobsearch/query.hpp"

namespace jobsearch {

/// BM25F parameters. Title matches count `title_weight` times a body match before length
/// normalisation, which is what makes "Data Engineer" in a title outrank a passing mention.
struct Bm25Params {
    double k1 = 1.2;
    double title_weight = 3.0;
    double body_weight = 1.0;
    double title_b = 0.5;
    double body_b = 0.75;
};

enum class SortOrder : std::uint8_t { Relevance, Newest, Salary };

struct SearchRequest {
    std::string query;
    std::size_t offset = 0;
    std::size_t limit = 10;
    SortOrder sort = SortOrder::Relevance;
    bool facets = true;
    bool snippets = true;
    /// "Today" for the days:N filter. 0 means the newest posted_day in the snapshot.
    std::uint32_t today = 0;
};

struct Hit {
    JobAd job;
    double score = 0.0;
    std::string snippet;  // matched words wrapped in [brackets]
};

struct FacetCount {
    std::string value;
    std::uint64_t count = 0;

    friend bool operator==(const FacetCount&, const FacetCount&) = default;
};

struct SearchResponse {
    std::uint64_t total_hits = 0;
    std::vector<Hit> hits;
    std::vector<FacetCount> locations;
    std::vector<FacetCount> contracts;
    std::vector<FacetCount> salary_bands;
    std::uint64_t generation = 0;
    std::string parsed;  // canonical query tree
};

inline constexpr std::size_t kMaxLimit = 100;
inline constexpr std::size_t kMaxOffset = 10'000;
inline constexpr std::size_t kMaxPrefixExpansions = 128;

/// Runs queries against one snapshot. Construct one per request (it is a shared_ptr copy);
/// it is immutable, so a single Searcher may also be shared between threads.
class Searcher {
  public:
    explicit Searcher(std::shared_ptr<const Snapshot> snapshot, Bm25Params params = {});

    [[nodiscard]] SearchResponse search(const SearchRequest& request) const;

    /// Inverse document frequency over the whole snapshot (all segments), so that a term's
    /// weight does not depend on which segment a document happens to sit in.
    [[nodiscard]] double idf(Field f, const std::string& term) const;

    using Matches = std::vector<std::pair<DocId, double>>;  // sorted by DocId
    /// Evaluates a parsed query against one segment. `today` is used by the days:N filter.
    [[nodiscard]] Matches evaluate(const QueryNode& node, std::size_t segment,
                                   std::uint32_t today = 0) const;

  private:
    struct Ctx {
        std::size_t segment = 0;
        std::uint32_t today = 0;
    };

    [[nodiscard]] Matches eval(const QueryNode& node, const Ctx& ctx) const;
    [[nodiscard]] Matches all_live(const Ctx& ctx) const;
    [[nodiscard]] Matches term(const QueryNode& node, const Ctx& ctx) const;
    [[nodiscard]] Matches phrase(const QueryNode& node, const Ctx& ctx) const;
    [[nodiscard]] Matches prefix(const QueryNode& node, const Ctx& ctx) const;
    [[nodiscard]] Matches conjunction(const QueryNode& node, const Ctx& ctx) const;
    [[nodiscard]] Matches disjunction(const QueryNode& node, const Ctx& ctx) const;
    [[nodiscard]] Matches filter(const QueryNode& node, const Ctx& ctx) const;
    [[nodiscard]] static bool passes(const FilterSpec& f, const JobAd& job, std::uint32_t today);
    [[nodiscard]] double field_norm(Field f, const Ctx& ctx, DocId doc) const;
    [[nodiscard]] double saturate(double tf_tilde) const;
    [[nodiscard]] double weight(Field f) const;

    std::shared_ptr<const Snapshot> snapshot_;
    Bm25Params params_;
    std::uint64_t total_docs_ = 0;
    std::uint32_t newest_day_ = 0;
    std::array<double, kFieldCount> avg_length_{1.0, 1.0};
};

/// Builds a short extract of `text` around the densest cluster of `terms`, wrapping each
/// matching word in [brackets]. Terms are analysed forms; a trailing '*' marks a prefix.
[[nodiscard]] std::string make_snippet(const std::string& text,
                                       const std::vector<std::string>& terms,
                                       std::size_t window_words = 24);

[[nodiscard]] std::string salary_band(std::uint32_t salary_max);

}  // namespace jobsearch
