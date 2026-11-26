#pragma once

#include <array>
#include <cstdint>
#include <filesystem>
#include <map>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "jobsearch/postings.hpp"
#include "jobsearch/types.hpp"

namespace jobsearch {

/// Throws InvalidJobError if the advert cannot be indexed.
void validate_job(const JobAd& job);

/// An immutable, self-contained slice of the index: term dictionaries and postings for each
/// field, per-document field lengths for BM25 and the stored adverts for display and filters.
/// Once built it is never modified, so any number of threads may read it without locks.
class Segment {
  public:
    using Dictionary = std::map<std::string, EncodedPostings, std::less<>>;

    /// Analyses and indexes `jobs`; document i gets local id i.
    [[nodiscard]] static Segment build(std::uint64_t id, std::span<const JobAd> jobs);

    [[nodiscard]] std::uint64_t id() const noexcept { return id_; }
    [[nodiscard]] std::uint32_t doc_count() const noexcept {
        return static_cast<std::uint32_t>(stored_.size());
    }
    [[nodiscard]] const JobAd& stored(DocId doc) const { return stored_.at(doc); }
    [[nodiscard]] std::uint32_t field_length(Field f, DocId doc) const {
        return lengths_[field_index(f)].at(doc);
    }
    [[nodiscard]] std::uint64_t total_field_length(Field f) const noexcept {
        return total_length_[field_index(f)];
    }

    /// Postings for an analysed term, or nullptr if the term does not occur in this field.
    [[nodiscard]] const EncodedPostings* postings(Field f, std::string_view term) const;
    [[nodiscard]] std::uint32_t doc_freq(Field f, std::string_view term) const;

    /// Up to `limit` dictionary terms beginning with `prefix`, in sorted order.
    [[nodiscard]] std::vector<std::string_view> expand_prefix(Field f, std::string_view prefix,
                                                              std::size_t limit) const;
    [[nodiscard]] std::size_t term_count(Field f) const noexcept {
        return dicts_[field_index(f)].size();
    }
    /// Bytes used by compressed postings (dictionary keys and stored fields excluded).
    [[nodiscard]] std::size_t postings_bytes() const noexcept;

    [[nodiscard]] std::vector<std::uint8_t> serialize() const;
    [[nodiscard]] static Segment deserialize(std::span<const std::uint8_t> bytes);

    void save(const std::filesystem::path& file) const;
    [[nodiscard]] static Segment load(const std::filesystem::path& file);

  private:
    std::uint64_t id_ = 0;
    std::array<Dictionary, kFieldCount> dicts_;
    std::array<std::vector<std::uint32_t>, kFieldCount> lengths_;
    std::array<std::uint64_t, kFieldCount> total_length_{};
    std::vector<JobAd> stored_;
};

/// Reads a whole file into memory; throws SearchError if it cannot be opened.
[[nodiscard]] std::vector<std::uint8_t> read_file(const std::filesystem::path& file);
/// Writes to `file.tmp`, flushes, then renames over `file`, so readers never see half a file.
void write_file_atomic(const std::filesystem::path& file, std::span<const std::uint8_t> bytes);

}  // namespace jobsearch
