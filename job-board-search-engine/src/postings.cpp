#include "jobsearch/postings.hpp"

#include <string>

namespace jobsearch {

void EncodedPostings::write(ByteWriter& out) const {
    out.varint(doc_count);
    out.varint(skips.size());
    for (const auto& s : skips) {
        out.varint(s.base);
        out.varint(s.last);
        out.varint(s.offset);
    }
    out.varint(bytes.size());
    out.raw(bytes);
}

EncodedPostings EncodedPostings::read(ByteReader& in) {
    EncodedPostings p;
    p.doc_count = in.varint32();
    const auto skip_count = in.varint();
    const auto expected_blocks =
        (static_cast<std::uint64_t>(p.doc_count) + kBlockSize - 1) / kBlockSize;
    if (skip_count != expected_blocks) {
        throw CorruptIndexError("skip table size does not match document count");
    }
    p.skips.reserve(static_cast<std::size_t>(skip_count));
    for (std::uint64_t i = 0; i < skip_count; ++i) {
        SkipEntry s;
        s.base = in.varint32();
        s.last = in.varint32();
        s.offset = in.varint32();
        p.skips.push_back(s);
    }
    const auto n = in.varint();
    if (n > in.remaining()) {
        throw CorruptIndexError("posting bytes past end of buffer");
    }
    const auto raw = in.raw(static_cast<std::size_t>(n));
    p.bytes.assign(raw.begin(), raw.end());
    for (const auto& s : p.skips) {
        if (s.offset > p.bytes.size()) {
            throw CorruptIndexError("skip offset past end of postings");
        }
    }
    return p;
}

void PostingsBuilder::add(DocId doc, std::uint32_t position) {
    if (has_doc_ && doc == doc_) {
        if (!positions_.empty() && position <= positions_.back()) {
            throw SearchError("positions must increase within a document");
        }
        positions_.push_back(position);
        return;
    }
    if (has_doc_ && doc < doc_) {
        throw SearchError("documents must be added in increasing order (got " +
                          std::to_string(doc) + " after " + std::to_string(doc_) + ")");
    }
    if (has_doc_) {
        flush_doc();
    }
    has_doc_ = true;
    doc_ = doc;
    positions_.assign(1, position);
}

void PostingsBuilder::flush_doc() {
    ByteWriter w;
    if (in_block_ == 0) {
        out_.skips.push_back(SkipEntry{out_.doc_count == 0 ? 0 : prev_doc_, doc_,
                                       static_cast<std::uint32_t>(out_.bytes.size())});
    }
    const DocId base = out_.skips.back().base;
    // The first document of the very first block is stored as-is (delta from 0 would
    // lose doc 0 vs "no previous doc"); every other delta is strictly positive.
    const DocId delta = (out_.doc_count == 0) ? doc_ : doc_ - (in_block_ == 0 ? base : prev_doc_);
    w.varint(delta);
    w.varint(positions_.size());
    std::uint32_t prev_pos = 0;
    for (const auto p : positions_) {
        w.varint(p - prev_pos);
        prev_pos = p;
    }
    out_.bytes.insert(out_.bytes.end(), w.bytes().begin(), w.bytes().end());
    out_.skips.back().last = doc_;
    prev_doc_ = doc_;
    ++out_.doc_count;
    if (++in_block_ == kBlockSize) {
        in_block_ = 0;
    }
}

EncodedPostings PostingsBuilder::finish() {
    if (has_doc_) {
        flush_doc();
        has_doc_ = false;
    }
    auto result = std::move(out_);
    out_ = EncodedPostings{};
    in_block_ = 0;
    return result;
}

PostingIterator::PostingIterator(const EncodedPostings& postings) : postings_(&postings) {
    if (postings_->doc_count > 0) {
        seek_block(0);
        decode_one();
    }
}

void PostingIterator::seek_block(std::size_t block) {
    block_ = block;
    pos_ = postings_->skips[block].offset;
    doc_ = postings_->skips[block].base;
    read_in_block_ = 0;
    read_total_ = static_cast<std::uint32_t>(block) * kBlockSize;
}

void PostingIterator::decode_one() {
    if (read_total_ >= postings_->doc_count) {
        valid_ = false;
        return;
    }
    const std::span<const std::uint8_t> bytes(postings_->bytes);
    const auto delta = static_cast<DocId>(decode_varint(bytes, pos_));
    doc_ = (read_total_ == 0) ? delta : doc_ + delta;
    const auto tf = static_cast<std::uint32_t>(decode_varint(bytes, pos_));
    positions_.resize(tf);
    std::uint32_t pos = 0;
    for (std::uint32_t i = 0; i < tf; ++i) {
        pos += static_cast<std::uint32_t>(decode_varint(bytes, pos_));
        positions_[i] = pos;
    }
    ++read_in_block_;
    ++read_total_;
    valid_ = true;
}

void PostingIterator::next() {
    if (!valid_) {
        return;
    }
    if (read_in_block_ == kBlockSize) {
        if (block_ + 1 >= postings_->skips.size()) {
            valid_ = false;
            return;
        }
        seek_block(block_ + 1);
    }
    decode_one();
}

void PostingIterator::advance(DocId target) {
    if (!valid_ || doc_ >= target) {
        return;
    }
    const auto& skips = postings_->skips;
    std::size_t block = block_;
    while (block + 1 < skips.size() && skips[block].last < target) {
        ++block;
    }
    if (block != block_) {
        blocks_skipped_ += static_cast<std::uint32_t>(block - block_);
        seek_block(block);
        decode_one();
    }
    while (valid_ && doc_ < target) {
        next();
    }
}

}  // namespace jobsearch
