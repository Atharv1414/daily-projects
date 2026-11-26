#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace jobsearch {

/// One indexed term and its word position. Stop words are dropped but still advance the
/// position counter, so phrase queries such as "head of data" keep their gaps.
struct Token {
    std::string term;
    std::uint32_t position = 0;

    friend bool operator==(const Token&, const Token&) = default;
};

/// Splits text into lower-cased words. Letters and digits form words; a trailing run of
/// '+' or '#' stays attached so "C++" and "C#" survive as "c++" and "c#".
[[nodiscard]] std::vector<std::string> split_words(std::string_view text);

[[nodiscard]] bool is_stopword(std::string_view word) noexcept;

/// A light, conservative English stemmer: plurals, -ing, -ed and a final silent e.
/// It is applied identically at index and query time, so it only has to be consistent.
[[nodiscard]] std::string stem(std::string_view word);

/// Full analysis chain used for indexing: split, drop stop words, stem.
[[nodiscard]] std::vector<Token> analyze(std::string_view text);

/// Analyses a single query word. Returns an empty string for stop words.
[[nodiscard]] std::string normalize_term(std::string_view word);

}  // namespace jobsearch
