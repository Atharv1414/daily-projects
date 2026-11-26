// Release-mode benchmark: indexing throughput, index size and query latency percentiles.
//   ./build/release/jobsearch_bench [jobs]

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

#include "jobsearch/corpus.hpp"
#include "jobsearch/index.hpp"
#include "jobsearch/searcher.hpp"

using namespace jobsearch;
using Clock = std::chrono::steady_clock;

namespace {

double percentile(std::vector<double> v, double p) {
    std::ranges::sort(v);
    const auto rank = static_cast<std::size_t>(p * static_cast<double>(v.size() - 1));
    return v[rank];
}

}  // namespace

int main(int argc, char** argv) {
    const std::size_t jobs = argc > 1 ? static_cast<std::size_t>(std::stoull(argv[1])) : 100'000;
    const auto corpus = generate_corpus(CorpusOptions{jobs, 42});
    std::size_t raw_bytes = 0;
    for (const auto& j : corpus) {
        raw_bytes += j.title.size() + j.body.size();
    }

    Index index;
    const auto t0 = Clock::now();
    for (const auto& j : corpus) {
        index.upsert(j);
    }
    index.refresh();
    const double index_s = std::chrono::duration<double>(Clock::now() - t0).count();
    const auto stats = index.stats();
    std::printf("corpus: %zu adverts, %.1f MiB of title+body text\n", jobs,
                static_cast<double>(raw_bytes) / (1024.0 * 1024.0));
    std::printf(
        "indexing: %.2f s (%.0f adverts/s), %zu segments after %llu flushes and %llu merges\n",
        index_s, static_cast<double>(jobs) / index_s, stats.segments,
        static_cast<unsigned long long>(stats.flushes),
        static_cast<unsigned long long>(stats.merges));
    std::printf("postings: %.1f MiB (%.0f%% of raw text, positions included)\n",
                static_cast<double>(stats.postings_bytes) / (1024.0 * 1024.0),
                100.0 * static_cast<double>(stats.postings_bytes) / static_cast<double>(raw_bytes));

    const std::vector<std::string> queries{
        "data engineer",
        "senior software engineer python",
        "\"class 1 licence\"",
        "\"pick and pack\" location:leeds",
        "(react OR typescript) remote:yes salary>=60k",
        "nurse -temporary days:14",
        "engin* location:london",
        "title:accountant ACCA",
        "chef OR cook OR kitchen",
        "salary>=80k contract:permanent",
    };
    const auto snap = index.snapshot();
    const Searcher searcher(snap);
    std::printf("\n%-46s %9s %9s %9s %9s\n", "query", "hits", "p50 ms", "p95 ms", "p99 ms");
    std::vector<double> all;
    for (const auto& q : queries) {
        SearchRequest req;
        req.query = q;
        std::vector<double> times;
        std::uint64_t hits = 0;
        for (int i = 0; i < 60; ++i) {
            const auto t = Clock::now();
            hits = searcher.search(req).total_hits;
            times.push_back(std::chrono::duration<double, std::milli>(Clock::now() - t).count());
        }
        all.insert(all.end(), times.begin(), times.end());
        std::printf("%-46s %9llu %9.2f %9.2f %9.2f\n", q.c_str(),
                    static_cast<unsigned long long>(hits), percentile(times, 0.5),
                    percentile(times, 0.95), percentile(times, 0.99));
    }
    std::printf("%-46s %9s %9.2f %9.2f %9.2f\n", "all queries", "", percentile(all, 0.5),
                percentile(all, 0.95), percentile(all, 0.99));

    // Throughput with several reader threads sharing one immutable snapshot.
    for (const unsigned threads : {1U, 4U}) {
        std::atomic<std::uint64_t> done{0};
        const auto start = Clock::now();
        {
            std::vector<std::jthread> pool;
            for (unsigned t = 0; t < threads; ++t) {
                pool.emplace_back([&, t] {
                    SearchRequest req;
                    req.facets = false;
                    for (std::size_t i = 0; i < 200; ++i) {
                        req.query = queries[(i + t) % queries.size()];
                        (void)searcher.search(req);
                        ++done;
                    }
                });
            }
        }
        const double secs = std::chrono::duration<double>(Clock::now() - start).count();
        std::printf("\n%u reader thread(s): %.0f queries/s", threads,
                    static_cast<double>(done.load()) / secs);
    }
    std::printf("\n");
    return 0;
}
