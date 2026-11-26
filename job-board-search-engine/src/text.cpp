#include "jobsearch/text.hpp"

#include <algorithm>
#include <array>

namespace jobsearch {
namespace {

constexpr std::array<std::string_view, 40> kStopwords = {
    "a",    "an",   "and",   "are",  "as",  "at",   "be",    "by",   "for",  "from",
    "has",  "have", "in",    "is",   "it",  "its",  "of",    "on",   "or",   "our",
    "that", "the",  "their", "this", "to",  "was",  "we",    "were", "will", "with",
    "you",  "your", "who",   "all",  "can", "into", "about", "also", "but",  "more"};

[[nodiscard]] constexpr bool is_word_char(char c) noexcept {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
}

[[nodiscard]] constexpr char to_lower(char c) noexcept {
    return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

[[nodiscard]] constexpr bool is_vowel(char c) noexcept {
    return c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u';
}

[[nodiscard]] bool ends_with(std::string_view s, std::string_view suffix) noexcept {
    return s.size() >= suffix.size() && s.substr(s.size() - suffix.size()) == suffix;
}

[[nodiscard]] bool has_vowel(std::string_view s) noexcept {
    return std::ranges::any_of(s, [](char c) { return is_vowel(c) || c == 'y'; });
}

/// "runn" -> "run", "plann" -> "plan", but keeps "ll", "ss" and "zz" ("install", "access").
void undouble(std::string& s) {
    if (s.size() < 3) {
        return;
    }
    const char last = s.back();
    if (last == s[s.size() - 2] && !is_vowel(last) && last != 'l' && last != 's' && last != 'z') {
        s.pop_back();
    }
}

}  // namespace

std::vector<std::string> split_words(std::string_view text) {
    std::vector<std::string> words;
    std::string current;
    for (std::size_t i = 0; i < text.size(); ++i) {
        const char c = text[i];
        if (is_word_char(c)) {
            current.push_back(to_lower(c));
            continue;
        }
        if ((c == '+' || c == '#') && !current.empty()) {
            current.push_back(c);
            continue;
        }
        if (!current.empty()) {
            words.push_back(std::move(current));
            current.clear();
        }
    }
    if (!current.empty()) {
        words.push_back(std::move(current));
    }
    return words;
}

bool is_stopword(std::string_view word) noexcept {
    return std::ranges::find(kStopwords, word) != kStopwords.end();
}

std::string stem(std::string_view word) {
    std::string s(word);
    // Short words, numbers and symbol-bearing tech terms ("c++", "c#", "sql") are left alone.
    if (s.size() <= 3 || !std::ranges::all_of(s, [](char c) { return c >= 'a' && c <= 'z'; })) {
        return s;
    }
    if (ends_with(s, "sses")) {
        s.erase(s.size() - 2);
    } else if (ends_with(s, "ies") && s.size() > 4) {
        s.replace(s.size() - 3, 3, "y");
    } else if (s.back() == 's' && !ends_with(s, "ss") && !ends_with(s, "us") &&
               !ends_with(s, "is")) {
        s.pop_back();
    }
    if (ends_with(s, "ing") && s.size() > 5 &&
        has_vowel(std::string_view(s).substr(0, s.size() - 3))) {
        s.erase(s.size() - 3);
        undouble(s);
    } else if (ends_with(s, "ed") && s.size() > 4 && !ends_with(s, "eed") &&
               has_vowel(std::string_view(s).substr(0, s.size() - 2))) {
        s.erase(s.size() - 2);
        undouble(s);
    }
    if (s.size() > 4 && s.back() == 'e') {
        s.pop_back();
    }
    return s;
}

std::vector<Token> analyze(std::string_view text) {
    std::vector<Token> tokens;
    std::uint32_t position = 0;
    for (const auto& word : split_words(text)) {
        if (!is_stopword(word)) {
            tokens.push_back(Token{stem(word), position});
        }
        ++position;
    }
    return tokens;
}

std::string normalize_term(std::string_view word) {
    const auto words = split_words(word);
    if (words.size() != 1 || is_stopword(words.front())) {
        return {};
    }
    return stem(words.front());
}

}  // namespace jobsearch
