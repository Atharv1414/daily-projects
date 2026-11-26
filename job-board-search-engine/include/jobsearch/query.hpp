#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "jobsearch/types.hpp"

namespace jobsearch {

enum class NodeKind : std::uint8_t { All, Term, Prefix, Phrase, And, Or, Not, Filter };

enum class FilterKind : std::uint8_t { MinSalary, Location, Contract, Remote, PostedWithin };

/// A non-scoring restriction on the stored fields of an advert.
struct FilterSpec {
    FilterKind kind = FilterKind::MinSalary;
    std::string text;          // Location (lower case)
    std::uint32_t number = 0;  // MinSalary in pounds, PostedWithin in days
    Contract contract = Contract::Permanent;
    bool flag = false;  // Remote
};

/// Parsed query tree. Terms are already analysed (lower-cased and stemmed), so the searcher
/// can look them up in the dictionary directly.
struct QueryNode {
    NodeKind kind = NodeKind::All;
    std::optional<Field> field;          // Term / Prefix / Phrase: nullopt = all fields
    std::vector<std::string> terms;      // one for Term/Prefix, several for Phrase
    std::vector<std::uint32_t> offsets;  // Phrase: word offset of each term
    std::vector<std::unique_ptr<QueryNode>> children;  // And / Or / Not
    FilterSpec filter;
};

using QueryPtr = std::unique_ptr<QueryNode>;

struct ParseLimits {
    std::size_t max_length = 1024;  // bytes of query text
    std::size_t max_clauses = 64;   // leaf terms, phrases, prefixes and filters
    std::size_t max_depth = 16;     // nested parentheses
};

/// Parses the job-board query language:
///
///   data engineer                  implicit AND
///   python OR scala                OR binds looser than AND
///   -recruiter, NOT agency         exclusion
///   "head of data"                 phrase (stop words keep their gap)
///   title:nurse  title:"band 6"    field restriction
///   engin*                         prefix (at least two letters)
///   salary>=45000 location:leeds contract:permanent remote:yes days:7   filters
///   (python OR go) -junior         grouping
///
/// An empty query matches every live advert. Throws QueryParseError with a byte position.
[[nodiscard]] QueryPtr parse_query(std::string_view text, const ParseLimits& limits = {});

/// A compact, canonical rendering of the tree, used by tests and `--explain`.
[[nodiscard]] std::string to_string(const QueryNode& node);

/// The analysed terms that should be highlighted in snippets (positive clauses only).
[[nodiscard]] std::vector<std::string> highlight_terms(const QueryNode& node);

}  // namespace jobsearch
