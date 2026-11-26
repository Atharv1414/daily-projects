#include "jobsearch/segment.hpp"

#include <fstream>
#include <iterator>
#include <limits>
#include <unordered_map>

#include "jobsearch/codec.hpp"
#include "jobsearch/text.hpp"

namespace jobsearch {
namespace {

constexpr std::uint32_t kSegmentMagic = 0x4745534AU;  // "JSEG" little endian
constexpr std::uint8_t kSegmentVersion = 1;
constexpr std::size_t kMaxBodyBytes = 64 * 1024;

void write_job(ByteWriter& w, const JobAd& job) {
    w.string(job.id);
    w.string(job.title);
    w.string(job.company);
    w.string(job.location);
    w.varint(job.salary_min);
    w.varint(job.salary_max);
    w.u8(static_cast<std::uint8_t>(job.contract));
    w.u8(job.remote ? 1 : 0);
    w.varint(job.posted_day);
    w.string(job.body);
}

JobAd read_job(ByteReader& r) {
    JobAd job;
    job.id = r.string();
    job.title = r.string();
    job.company = r.string();
    job.location = r.string();
    job.salary_min = r.varint32();
    job.salary_max = r.varint32();
    const auto contract = r.u8();
    if (contract > static_cast<std::uint8_t>(Contract::Temporary)) {
        throw CorruptIndexError("unknown contract type in stored job");
    }
    job.contract = static_cast<Contract>(contract);
    job.remote = r.u8() != 0;
    job.posted_day = r.varint32();
    job.body = r.string();
    return job;
}

}  // namespace

void validate_job(const JobAd& job) {
    if (job.id.empty()) {
        throw InvalidJobError("job id is required");
    }
    if (job.title.empty()) {
        throw InvalidJobError("job " + job.id + " has no title");
    }
    if (job.salary_max < job.salary_min) {
        throw InvalidJobError("job " + job.id + " has salary_max below salary_min");
    }
    if (job.body.size() > kMaxBodyBytes) {
        throw InvalidJobError("job " + job.id + " body is over 64 KiB");
    }
}

Segment Segment::build(std::uint64_t id, std::span<const JobAd> jobs) {
    if (jobs.size() >= std::numeric_limits<DocId>::max()) {
        throw SearchError("too many documents for one segment");
    }
    Segment seg;
    seg.id_ = id;
    seg.stored_.assign(jobs.begin(), jobs.end());
    std::array<std::unordered_map<std::string, PostingsBuilder>, kFieldCount> builders;
    for (std::size_t i = 0; i < jobs.size(); ++i) {
        validate_job(jobs[i]);
        const auto doc = static_cast<DocId>(i);
        const std::array<std::string_view, kFieldCount> texts{jobs[i].title, jobs[i].body};
        for (std::size_t f = 0; f < kFieldCount; ++f) {
            const auto tokens = analyze(texts[f]);
            const auto length = static_cast<std::uint32_t>(tokens.size());
            seg.lengths_[f].push_back(length);
            seg.total_length_[f] += length;
            for (const auto& token : tokens) {
                builders[f][token.term].add(doc, token.position);
            }
        }
    }
    for (std::size_t f = 0; f < kFieldCount; ++f) {
        for (auto& [term, builder] : builders[f]) {
            seg.dicts_[f].emplace(term, builder.finish());
        }
    }
    return seg;
}

const EncodedPostings* Segment::postings(Field f, std::string_view term) const {
    const auto& dict = dicts_[field_index(f)];
    const auto it = dict.find(term);
    return it == dict.end() ? nullptr : &it->second;
}

std::uint32_t Segment::doc_freq(Field f, std::string_view term) const {
    const auto* p = postings(f, term);
    return p == nullptr ? 0 : p->doc_count;
}

std::vector<std::string_view> Segment::expand_prefix(Field f, std::string_view prefix,
                                                     std::size_t limit) const {
    std::vector<std::string_view> out;
    const auto& dict = dicts_[field_index(f)];
    for (auto it = dict.lower_bound(prefix); it != dict.end() && out.size() < limit; ++it) {
        if (std::string_view(it->first).substr(0, prefix.size()) != prefix) {
            break;
        }
        out.emplace_back(it->first);
    }
    return out;
}

std::size_t Segment::postings_bytes() const noexcept {
    std::size_t total = 0;
    for (const auto& dict : dicts_) {
        for (const auto& [term, p] : dict) {
            total += p.bytes.size() + p.skips.size() * sizeof(SkipEntry);
        }
    }
    return total;
}

std::vector<std::uint8_t> Segment::serialize() const {
    ByteWriter w;
    w.u32(kSegmentMagic);
    w.u8(kSegmentVersion);
    w.varint(id_);
    w.varint(stored_.size());
    for (std::size_t f = 0; f < kFieldCount; ++f) {
        for (const auto len : lengths_[f]) {
            w.varint(len);
        }
        w.varint(dicts_[f].size());
        for (const auto& [term, p] : dicts_[f]) {
            w.string(term);
            p.write(w);
        }
    }
    for (const auto& job : stored_) {
        write_job(w, job);
    }
    const auto checksum = crc32(w.bytes());
    w.u32(checksum);
    return w.take();
}

Segment Segment::deserialize(std::span<const std::uint8_t> bytes) {
    if (bytes.size() < 9) {
        throw CorruptIndexError("segment file too small");
    }
    const auto body = bytes.first(bytes.size() - 4);
    ByteReader tail(bytes.last(4));
    if (crc32(body) != tail.u32()) {
        throw CorruptIndexError("segment checksum mismatch");
    }
    ByteReader r(body);
    if (r.u32() != kSegmentMagic) {
        throw CorruptIndexError("not a segment file (bad magic)");
    }
    if (const auto version = r.u8(); version != kSegmentVersion) {
        throw CorruptIndexError("unsupported segment version " + std::to_string(version));
    }
    Segment seg;
    seg.id_ = r.varint();
    const auto docs = r.varint();
    if (docs > r.remaining()) {  // every document needs at least one byte per field length
        throw CorruptIndexError("document count larger than file");
    }
    for (std::size_t f = 0; f < kFieldCount; ++f) {
        seg.lengths_[f].reserve(static_cast<std::size_t>(docs));
        for (std::uint64_t i = 0; i < docs; ++i) {
            const auto len = r.varint32();
            seg.lengths_[f].push_back(len);
            seg.total_length_[f] += len;
        }
        const auto terms = r.varint();
        for (std::uint64_t i = 0; i < terms; ++i) {
            auto term = r.string();
            auto postings = EncodedPostings::read(r);
            if (postings.doc_count > docs) {
                throw CorruptIndexError("posting list longer than segment");
            }
            seg.dicts_[f].emplace_hint(seg.dicts_[f].end(), std::move(term), std::move(postings));
        }
    }
    seg.stored_.reserve(static_cast<std::size_t>(docs));
    for (std::uint64_t i = 0; i < docs; ++i) {
        seg.stored_.push_back(read_job(r));
    }
    if (!r.at_end()) {
        throw CorruptIndexError("trailing bytes after segment");
    }
    return seg;
}

void Segment::save(const std::filesystem::path& file) const {
    write_file_atomic(file, serialize());
}

Segment Segment::load(const std::filesystem::path& file) { return deserialize(read_file(file)); }

std::vector<std::uint8_t> read_file(const std::filesystem::path& file) {
    std::ifstream in(file, std::ios::binary);
    if (!in) {
        throw SearchError("cannot open " + file.string());
    }
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

void write_file_atomic(const std::filesystem::path& file, std::span<const std::uint8_t> bytes) {
    auto tmp = file;
    tmp += ".tmp";
    {
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        if (!out) {
            throw SearchError("cannot write " + tmp.string());
        }
        out.write(reinterpret_cast<const char*>(bytes.data()),
                  static_cast<std::streamsize>(bytes.size()));
        out.flush();
        if (!out) {
            throw SearchError("short write to " + tmp.string());
        }
    }
    std::filesystem::rename(tmp, file);
}

}  // namespace jobsearch
