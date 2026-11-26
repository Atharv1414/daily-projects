#pragma once

#include <cstdint>
#include <span>
#include <vector>

#include "jobsearch/codec.hpp"
#include "jobsearch/types.hpp"

namespace jobsearch {

/// Documents per compressed block. Each block has a skip entry, so `advance()` can jump over
/// whole blocks without decoding them.
inline constexpr std::uint32_t kBlockSize = 128;

struct SkipEntry {
    DocId base = 0;            // doc id the first delta in the block is relative to
    DocId last = 0;            // last doc id in the block
    std::uint32_t offset = 0;  // byte offset of the block in `bytes`

    friend bool operator==(const SkipEntry&, const SkipEntry&) = default;
};

/// A term's posting list: doc-id deltas, term frequency and position deltas, all varints.
struct EncodedPostings {
    std::uint32_t doc_count = 0;
    std::vector<std::uint8_t> bytes;
    std::vector<SkipEntry> skips;

    void write(ByteWriter& out) const;
    [[nodiscard]] static EncodedPostings read(ByteReader& in);

    friend bool operator==(const EncodedPostings&, const EncodedPostings&) = default;
};

/// Builds a posting list. Documents must arrive in increasing order, positions increasing
/// within a document; both are checked so a bad caller fails loudly instead of corrupting.
class PostingsBuilder {
  public:
    void add(DocId doc, std::uint32_t position);
    [[nodiscard]] EncodedPostings finish();

  private:
    void flush_doc();

    EncodedPostings out_;
    bool has_doc_ = false;
    DocId doc_ = 0;
    DocId prev_doc_ = 0;
    std::vector<std::uint32_t> positions_;
    std::uint32_t in_block_ = 0;
};

/// Forward-only cursor over an EncodedPostings. Cheap to create; not thread-safe, but any
/// number of iterators can read the same immutable postings concurrently.
class PostingIterator {
  public:
    explicit PostingIterator(const EncodedPostings& postings);

    [[nodiscard]] bool valid() const noexcept { return valid_; }
    [[nodiscard]] DocId doc() const noexcept { return doc_; }
    [[nodiscard]] std::uint32_t tf() const noexcept {
        return static_cast<std::uint32_t>(positions_.size());
    }
    [[nodiscard]] std::span<const std::uint32_t> positions() const noexcept { return positions_; }

    void next();
    /// Moves to the first document >= target (no-op if already there).
    void advance(DocId target);
    /// Number of blocks skipped by advance() so far; exposed for tests and benchmarks.
    [[nodiscard]] std::uint32_t blocks_skipped() const noexcept { return blocks_skipped_; }

  private:
    void seek_block(std::size_t block);
    void decode_one();

    const EncodedPostings* postings_;
    std::size_t block_ = 0;
    std::size_t pos_ = 0;
    std::uint32_t read_in_block_ = 0;
    std::uint32_t read_total_ = 0;
    DocId doc_ = 0;
    bool valid_ = false;
    std::vector<std::uint32_t> positions_;
    std::uint32_t blocks_skipped_ = 0;
};

}  // namespace jobsearch
