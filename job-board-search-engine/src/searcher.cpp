#include "jobsearch/searcher.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

#include "jobsearch/text.hpp"

namespace jobsearch {
namespace {

using Matches = Searcher::Matches;

constexpr std::array<Field, kFieldCount> kAllFields{Field::Title, Field::Body};

std::vector<Field> fields_for(const QueryNode& n) {
    if (n.field) {
        return {*n.field};
    }
    return {kAllFields.begin(), kAllFields.end()};
}

/// Sorted-merge intersection; scores add up.
Matches intersect(const Matches& a, const Matches& b) {
    Matches out;
    std::size_t i = 0;
    std::size_t j = 0;
    while (i < a.size() && j < b.size()) {
        if (a[i].first < b[j].first) {
            ++i;
        } else if (b[j].first < a[i].first) {
            ++j;
        } else {
            out.emplace_back(a[i].first, a[i].second + b[j].second);
            ++i;
            ++j;
        }
    }
    return out;
}

/// Sorted-merge union; scores add up for documents in both lists.
Matches unite(const Matches& a, const Matches& b) {
    Matches out;
    out.reserve(a.size() + b.size());
    std::size_t i = 0;
    std::size_t j = 0;
    while (i < a.size() || j < b.size()) {
        if (j == b.size() || (i < a.size() && a[i].first < b[j].first)) {
            out.push_back(a[i++]);
        } else if (i == a.size() || b[j].first < a[i].first) {
            out.push_back(b[j++]);
        } else {
            out.emplace_back(a[i].first, a[i].second + b[j].second);
            ++i;
            ++j;
        }
    }
    return out;
}

Matches subtract(const Matches& a, const Matches& b) {
    Matches out;
    std::size_t j = 0;
    for (const auto& m : a) {
        while (j < b.size() && b[j].first < m.first) {
            ++j;
        }
        if (j == b.size() || b[j].first != m.first) {
            out.push_back(m);
        }
    }
    return out;
}

std::string lower(std::string_view s) {
    std::string out(s);
    std::ranges::transform(out, out.begin(), [](char c) {
        return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
    });
    return out;
}

/// Counts phrase occurrences in one document given each term's positions and offsets.
std::uint32_t phrase_freq(const std::vector<std::span<const std::uint32_t>>& positions,
                          const std::vector<std::uint32_t>& offsets) {
    std::uint32_t freq = 0;
    for (const auto start : positions.front()) {
        bool ok = true;
        for (std::size_t t = 1; t < positions.size() && ok; ++t) {
            const auto want = start + offsets[t];
            ok = std::ranges::binary_search(positions[t], want);
        }
        if (ok) {
            ++freq;
        }
    }
    return freq;
}

struct ScoredRef {
    std::size_t segment = 0;
    DocId doc = 0;
    double score = 0.0;
};

}  // namespace

std::string_view contract_name(Contract c) noexcept {
    switch (c) {
        case Contract::Permanent:
            return "permanent";
        case Contract::Contract:
            return "contract";
        case Contract::Temporary:
            return "temporary";
    }
    return "unknown";
}

std::string salary_band(std::uint32_t salary_max) {
    if (salary_max < 25'000) {
        return "under £25k";
    }
    if (salary_max < 35'000) {
        return "£25k–£35k";
    }
    if (salary_max < 50'000) {
        return "£35k–£50k";
    }
    if (salary_max < 70'000) {
        return "£50k–£70k";
    }
    return "£70k+";
}

Searcher::Searcher(std::shared_ptr<const Snapshot> snapshot, Bm25Params params)
    : snapshot_(std::move(snapshot)), params_(params) {
    std::array<std::uint64_t, kFieldCount> totals{};
    for (const auto& view : snapshot_->segments) {
        total_docs_ += view.segment->doc_count();
        for (std::size_t f = 0; f < kFieldCount; ++f) {
            totals[f] += view.segment->total_field_length(static_cast<Field>(f));
        }
        for (DocId d = 0; d < view.segment->doc_count(); ++d) {
            newest_day_ = std::max(newest_day_, view.segment->stored(d).posted_day);
        }
    }
    for (std::size_t f = 0; f < kFieldCount; ++f) {
        if (total_docs_ > 0 && totals[f] > 0) {
            avg_length_[f] = static_cast<double>(totals[f]) / static_cast<double>(total_docs_);
        }
    }
}

double Searcher::idf(Field f, const std::string& term) const {
    std::uint64_t df = 0;
    for (const auto& view : snapshot_->segments) {
        df += view.segment->doc_freq(f, term);
    }
    const auto n = static_cast<double>(total_docs_);
    const auto d = static_cast<double>(df);
    return std::log(1.0 + (n - d + 0.5) / (d + 0.5));
}

double Searcher::weight(Field f) const {
    return f == Field::Title ? params_.title_weight : params_.body_weight;
}

double Searcher::field_norm(Field f, const Ctx& ctx, DocId doc) const {
    const auto& seg = *snapshot_->segments[ctx.segment].segment;
    const double b = f == Field::Title ? params_.title_b : params_.body_b;
    const double len = static_cast<double>(seg.field_length(f, doc));
    return 1.0 - b + b * len / avg_length_[field_index(f)];
}

double Searcher::saturate(double tf_tilde) const {
    return tf_tilde * (params_.k1 + 1.0) / (params_.k1 + tf_tilde);
}

Matches Searcher::evaluate(const QueryNode& node, std::size_t segment, std::uint32_t today) const {
    return eval(node, Ctx{segment, today == 0 ? newest_day_ : today});
}

Matches Searcher::eval(const QueryNode& node, const Ctx& ctx) const {
    switch (node.kind) {
        case NodeKind::All:
            return all_live(ctx);
        case NodeKind::Term:
            return term(node, ctx);
        case NodeKind::Phrase:
            return phrase(node, ctx);
        case NodeKind::Prefix:
            return prefix(node, ctx);
        case NodeKind::And:
            return conjunction(node, ctx);
        case NodeKind::Or:
            return disjunction(node, ctx);
        case NodeKind::Not:
            return subtract(all_live(ctx), eval(*node.children.front(), ctx));
        case NodeKind::Filter:
            return filter(node, ctx);
    }
    return {};
}

Matches Searcher::all_live(const Ctx& ctx) const {
    const auto& view = snapshot_->segments[ctx.segment];
    Matches out;
    out.reserve(view.live_docs());
    for (DocId d = 0; d < view.segment->doc_count(); ++d) {
        if (view.is_live(d)) {
            out.emplace_back(d, 0.0);
        }
    }
    return out;
}

Matches Searcher::term(const QueryNode& node, const Ctx& ctx) const {
    const auto& view = snapshot_->segments[ctx.segment];
    const auto& term = node.terms.front();
    // BM25F: combine weighted, length-normalised term frequencies across fields first,
    // then saturate once, so a word in both title and body is not double-counted.
    std::vector<std::pair<Field, PostingIterator>> its;
    double best_idf = 0.0;
    for (const auto f : fields_for(node)) {
        best_idf = std::max(best_idf, idf(f, term));
        if (const auto* p = view.segment->postings(f, term)) {
            its.emplace_back(f, PostingIterator(*p));
        }
    }
    Matches out;
    while (true) {
        DocId doc = 0;
        bool any = false;
        for (const auto& [f, it] : its) {
            if (it.valid() && (!any || it.doc() < doc)) {
                doc = it.doc();
                any = true;
            }
        }
        if (!any) {
            break;
        }
        double tf_tilde = 0.0;
        for (auto& [f, it] : its) {
            if (it.valid() && it.doc() == doc) {
                tf_tilde += weight(f) * static_cast<double>(it.tf()) / field_norm(f, ctx, doc);
                it.next();
            }
        }
        if (view.is_live(doc)) {
            out.emplace_back(doc, best_idf * saturate(tf_tilde));
        }
    }
    return out;
}

Matches Searcher::phrase(const QueryNode& node, const Ctx& ctx) const {
    const auto& view = snapshot_->segments[ctx.segment];
    double phrase_idf = 0.0;
    for (const auto& t : node.terms) {
        double best = 0.0;
        for (const auto f : fields_for(node)) {
            best = std::max(best, idf(f, t));
        }
        phrase_idf += best;
    }
    std::map<DocId, double> tf_tilde;
    for (const auto f : fields_for(node)) {
        std::vector<PostingIterator> its;
        bool missing = false;
        for (const auto& t : node.terms) {
            const auto* p = view.segment->postings(f, t);
            if (p == nullptr) {
                missing = true;
                break;
            }
            its.emplace_back(*p);
        }
        if (missing) {
            continue;
        }
        // Rarest term leads; the others leapfrog to it using their skip tables.
        std::size_t lead = 0;
        for (std::size_t i = 1; i < its.size(); ++i) {
            if (view.segment->postings(f, node.terms[i])->doc_count <
                view.segment->postings(f, node.terms[lead])->doc_count) {
                lead = i;
            }
        }
        while (its[lead].valid()) {
            const DocId target = its[lead].doc();
            bool all = true;
            DocId overshoot = target;
            for (std::size_t i = 0; i < its.size(); ++i) {
                if (i == lead) {
                    continue;
                }
                its[i].advance(target);
                if (!its[i].valid()) {
                    all = false;
                    overshoot = std::numeric_limits<DocId>::max();
                    break;
                }
                if (its[i].doc() != target) {
                    all = false;
                    overshoot = std::max(overshoot, its[i].doc());
                }
            }
            if (overshoot == std::numeric_limits<DocId>::max()) {
                break;
            }
            if (all && view.is_live(target)) {
                std::vector<std::span<const std::uint32_t>> positions;
                positions.reserve(its.size());
                for (const auto& it : its) {
                    positions.push_back(it.positions());
                }
                if (const auto freq = phrase_freq(positions, node.offsets); freq > 0) {
                    tf_tilde[target] +=
                        weight(f) * static_cast<double>(freq) / field_norm(f, ctx, target);
                }
            }
            if (all) {
                its[lead].next();
            } else {
                its[lead].advance(overshoot);
            }
        }
    }
    Matches out;
    out.reserve(tf_tilde.size());
    for (const auto& [doc, tf] : tf_tilde) {
        out.emplace_back(doc, phrase_idf * saturate(tf));
    }
    return out;
}

Matches Searcher::prefix(const QueryNode& node, const Ctx& ctx) const {
    // Constant score: an expansion such as engin* -> engine, engineer, engineering should
    // not let a common expansion drown out the rest of the query.
    const auto& view = snapshot_->segments[ctx.segment];
    std::set<DocId> docs;
    for (const auto f : fields_for(node)) {
        for (const auto term :
             view.segment->expand_prefix(f, node.terms.front(), kMaxPrefixExpansions)) {
            for (PostingIterator it(*view.segment->postings(f, term)); it.valid(); it.next()) {
                if (view.is_live(it.doc())) {
                    docs.insert(it.doc());
                }
            }
        }
    }
    Matches out;
    out.reserve(docs.size());
    for (const auto d : docs) {
        out.emplace_back(d, 1.0);
    }
    return out;
}

Matches Searcher::conjunction(const QueryNode& node, const Ctx& ctx) const {
    std::vector<const QueryNode*> positive;
    std::vector<const QueryNode*> negative;
    std::vector<const QueryNode*> filters;
    for (const auto& c : node.children) {
        if (c->kind == NodeKind::Not) {
            negative.push_back(c->children.front().get());
        } else if (c->kind == NodeKind::Filter) {
            filters.push_back(c.get());
        } else {
            positive.push_back(c.get());
        }
    }
    Matches acc;
    if (positive.empty()) {
        acc = all_live(ctx);
    } else {
        std::vector<Matches> lists;
        for (const auto* p : positive) {
            lists.push_back(eval(*p, ctx));
        }
        // Intersect smallest first so intermediate results stay small.
        std::ranges::sort(lists,
                          [](const Matches& x, const Matches& y) { return x.size() < y.size(); });
        acc = std::move(lists.front());
        for (std::size_t i = 1; i < lists.size() && !acc.empty(); ++i) {
            acc = intersect(acc, lists[i]);
        }
    }
    if (!filters.empty()) {
        const auto& seg = *snapshot_->segments[ctx.segment].segment;
        std::erase_if(acc, [&](const auto& m) {
            return !std::ranges::all_of(filters, [&](const QueryNode* f) {
                return passes(f->filter, seg.stored(m.first), ctx.today);
            });
        });
    }
    for (const auto* n : negative) {
        if (acc.empty()) {
            break;
        }
        acc = subtract(acc, eval(*n, ctx));
    }
    return acc;
}

Matches Searcher::disjunction(const QueryNode& node, const Ctx& ctx) const {
    Matches acc;
    for (const auto& c : node.children) {
        acc = unite(acc, eval(*c, ctx));
    }
    return acc;
}

Matches Searcher::filter(const QueryNode& node, const Ctx& ctx) const {
    const auto& seg = *snapshot_->segments[ctx.segment].segment;
    auto acc = all_live(ctx);
    std::erase_if(
        acc, [&](const auto& m) { return !passes(node.filter, seg.stored(m.first), ctx.today); });
    return acc;
}

bool Searcher::passes(const FilterSpec& f, const JobAd& job, std::uint32_t today) {
    switch (f.kind) {
        case FilterKind::MinSalary:
            return job.salary_max >= f.number;
        case FilterKind::Location:
            return lower(job.location) == f.text;
        case FilterKind::Contract:
            return job.contract == f.contract;
        case FilterKind::Remote:
            return job.remote == f.flag;
        case FilterKind::PostedWithin:
            return job.posted_day + f.number >= today;
    }
    return false;
}

SearchResponse Searcher::search(const SearchRequest& request) const {
    if (request.limit == 0 || request.limit > kMaxLimit) {
        throw SearchError("limit must be between 1 and " + std::to_string(kMaxLimit));
    }
    if (request.offset > kMaxOffset) {
        throw SearchError("offset must be at most " + std::to_string(kMaxOffset));
    }
    const auto query = parse_query(request.query);
    SearchResponse response;
    response.parsed = to_string(*query);
    response.generation = snapshot_->generation;

    std::vector<ScoredRef> candidates;
    std::map<std::string, std::uint64_t> locations;
    std::map<std::string, std::uint64_t> contracts;
    std::map<std::string, std::uint64_t> bands;
    for (std::size_t s = 0; s < snapshot_->segments.size(); ++s) {
        const auto& seg = *snapshot_->segments[s].segment;
        for (const auto& [doc, score] : evaluate(*query, s, request.today)) {
            candidates.push_back(ScoredRef{s, doc, score});
            if (request.facets) {
                const auto& job = seg.stored(doc);
                ++locations[job.location];
                ++contracts[std::string(contract_name(job.contract))];
                ++bands[salary_band(job.salary_max)];
            }
        }
    }
    response.total_hits = candidates.size();

    const auto job_of = [&](const ScoredRef& r) -> const JobAd& {
        return snapshot_->segments[r.segment].segment->stored(r.doc);
    };
    const auto better = [&](const ScoredRef& a, const ScoredRef& b) {
        const auto& ja = job_of(a);
        const auto& jb = job_of(b);
        switch (request.sort) {
            case SortOrder::Newest:
                if (ja.posted_day != jb.posted_day) {
                    return ja.posted_day > jb.posted_day;
                }
                break;
            case SortOrder::Salary:
                if (ja.salary_max != jb.salary_max) {
                    return ja.salary_max > jb.salary_max;
                }
                break;
            case SortOrder::Relevance:
                break;
        }
        if (a.score != b.score) {
            return a.score > b.score;
        }
        if (ja.posted_day != jb.posted_day) {
            return ja.posted_day > jb.posted_day;
        }
        return ja.id < jb.id;  // total order, so pages never overlap or skip
    };
    const auto wanted = std::min(candidates.size(), request.offset + request.limit);
    std::partial_sort(candidates.begin(), candidates.begin() + static_cast<std::ptrdiff_t>(wanted),
                      candidates.end(), better);

    const auto highlights = highlight_terms(*query);
    for (std::size_t i = request.offset; i < wanted; ++i) {
        Hit hit;
        hit.job = job_of(candidates[i]);
        hit.score = candidates[i].score;
        if (request.snippets) {
            hit.snippet = make_snippet(hit.job.body, highlights);
        }
        response.hits.push_back(std::move(hit));
    }
    const auto to_facets = [](const std::map<std::string, std::uint64_t>& m) {
        std::vector<FacetCount> out;
        for (const auto& [value, count] : m) {
            out.push_back(FacetCount{value, count});
        }
        std::ranges::stable_sort(out,
                                 [](const auto& a, const auto& b) { return a.count > b.count; });
        return out;
    };
    response.locations = to_facets(locations);
    response.contracts = to_facets(contracts);
    response.salary_bands = to_facets(bands);
    return response;
}

std::string make_snippet(const std::string& text, const std::vector<std::string>& terms,
                         std::size_t window_words) {
    struct Word {
        std::size_t begin = 0;
        std::size_t end = 0;
        bool hit = false;
    };
    std::vector<Word> words;
    const auto is_word = [](char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
               c == '+' || c == '#';
    };
    for (std::size_t i = 0; i < text.size();) {
        if (!is_word(text[i])) {
            ++i;
            continue;
        }
        const std::size_t start = i;
        while (i < text.size() && is_word(text[i])) {
            ++i;
        }
        const auto analysed = normalize_term(std::string_view(text).substr(start, i - start));
        bool hit = false;
        if (!analysed.empty()) {
            hit = std::ranges::any_of(terms, [&](const std::string& t) {
                if (t.ends_with('*')) {
                    return analysed.starts_with(std::string_view(t).substr(0, t.size() - 1));
                }
                return analysed == t;
            });
        }
        words.push_back(Word{start, i, hit});
    }
    if (words.empty()) {
        return {};
    }
    const std::size_t window = std::min(window_words, words.size());
    std::size_t best_start = 0;
    std::size_t best_hits = 0;
    std::size_t hits = 0;
    for (std::size_t i = 0; i < words.size(); ++i) {
        hits += words[i].hit ? 1 : 0;
        if (i >= window) {
            hits -= words[i - window].hit ? 1 : 0;
        }
        if (i + 1 >= window && hits > best_hits) {
            best_hits = hits;
            best_start = i + 1 - window;
        }
    }
    std::string out = best_start > 0 ? "… " : "";
    std::size_t cursor = words[best_start].begin;
    const std::size_t last = best_start + window - 1;
    for (std::size_t i = best_start; i <= last; ++i) {
        out.append(text, cursor, words[i].begin - cursor);
        const auto w = std::string_view(text).substr(words[i].begin, words[i].end - words[i].begin);
        if (words[i].hit) {
            out += "[";
            out += w;
            out += "]";
        } else {
            out += w;
        }
        cursor = words[i].end;
    }
    if (last + 1 < words.size()) {
        out += " …";
    } else {
        out.append(text, cursor, std::string::npos);
    }
    return out;
}

}  // namespace jobsearch
