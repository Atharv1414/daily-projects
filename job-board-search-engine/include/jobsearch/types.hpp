#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>

namespace jobsearch {

/// Segment-local document number. Segments are capped well below 2^32 documents.
using DocId = std::uint32_t;

/// The two searchable text fields. Everything else on a job advert is a filter column.
enum class Field : std::uint8_t { Title = 0, Body = 1 };
inline constexpr std::size_t kFieldCount = 2;

[[nodiscard]] constexpr std::size_t field_index(Field f) noexcept {
    return static_cast<std::size_t>(f);
}

[[nodiscard]] constexpr std::string_view field_name(Field f) noexcept {
    return f == Field::Title ? "title" : "body";
}

enum class Contract : std::uint8_t { Permanent = 0, Contract = 1, Temporary = 2 };

[[nodiscard]] std::string_view contract_name(Contract c) noexcept;

/// A job advert as posted by a recruiter. `posted_day` counts days since the board opened.
struct JobAd {
    std::string id;
    std::string title;
    std::string company;
    std::string location;
    std::uint32_t salary_min = 0;  // pounds per year
    std::uint32_t salary_max = 0;
    Contract contract = Contract::Permanent;
    bool remote = false;
    std::uint32_t posted_day = 0;
    std::string body;

    friend bool operator==(const JobAd&, const JobAd&) = default;
};

/// Base class for every error the library throws on purpose.
class SearchError : public std::runtime_error {
  public:
    using std::runtime_error::runtime_error;
};

/// A query string that does not follow the grammar. `position` is a byte offset.
class QueryParseError : public SearchError {
  public:
    QueryParseError(const std::string& message, std::size_t position)
        : SearchError(message + " at position " + std::to_string(position)), position_(position) {}
    [[nodiscard]] std::size_t position() const noexcept { return position_; }

  private:
    std::size_t position_;
};

/// An index file failed its magic, version or checksum check.
class CorruptIndexError : public SearchError {
  public:
    using SearchError::SearchError;
};

/// A job advert that cannot be indexed (missing id, salary range upside down, ...).
class InvalidJobError : public SearchError {
  public:
    using SearchError::SearchError;
};

}  // namespace jobsearch
