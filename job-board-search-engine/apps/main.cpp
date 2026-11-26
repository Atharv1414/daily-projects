// jobsearch: command-line front end for the job-board search engine.
//
//   jobsearch build  --dir idx [--jobs 100000] [--seed 42]
//   jobsearch search --dir idx [--limit 10] [--offset 0] [--sort relevance|newest|salary] QUERY
//   jobsearch close  --dir idx JOB_ID
//   jobsearch stats  --dir idx
//   jobsearch demo   [--jobs 20000]

#include <chrono>
#include <cstdio>
#include <iostream>
#include <map>
#include <string>
#include <vector>

#include "jobsearch/corpus.hpp"
#include "jobsearch/index.hpp"
#include "jobsearch/searcher.hpp"

namespace {

using namespace jobsearch;
using Clock = std::chrono::steady_clock;

struct Args {
    std::string command;
    std::map<std::string, std::string> options;
    std::vector<std::string> positional;
};

Args parse_args(int argc, char** argv) {
    Args args;
    const std::vector<std::string> raw(argv + 1, argv + argc);
    for (std::size_t i = 0; i < raw.size(); ++i) {
        const auto& a = raw[i];
        if (args.command.empty() && !a.starts_with("--")) {
            args.command = a;
        } else if (a == "--no-facets" || a == "--explain") {
            args.options[a.substr(2)] = "1";
        } else if (a.starts_with("--")) {
            if (i + 1 >= raw.size()) {
                throw SearchError("missing value for " + a);
            }
            args.options[a.substr(2)] = raw[++i];
        } else {
            args.positional.push_back(a);
        }
    }
    return args;
}

std::string option(const Args& args, const std::string& key, const std::string& fallback) {
    const auto it = args.options.find(key);
    return it == args.options.end() ? fallback : it->second;
}

std::size_t number(const Args& args, const std::string& key, std::size_t fallback) {
    const auto text = option(args, key, "");
    return text.empty() ? fallback : static_cast<std::size_t>(std::stoull(text));
}

std::string joined(const std::vector<std::string>& parts) {
    std::string out;
    for (const auto& p : parts) {
        out += (out.empty() ? "" : " ") + p;
    }
    return out;
}

double ms_since(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

std::string salary_text(const JobAd& job) {
    if (job.salary_max == 0) {
        return "salary not given";
    }
    return "£" + std::to_string(job.salary_min / 1000) + "k–£" +
           std::to_string(job.salary_max / 1000) + "k";
}

void print_facets(const char* name, const std::vector<FacetCount>& facets, std::size_t top) {
    std::cout << "  " << name << ":";
    for (std::size_t i = 0; i < facets.size() && i < top; ++i) {
        std::cout << (i == 0 ? " " : ", ") << facets[i].value << " (" << facets[i].count << ")";
    }
    std::cout << "\n";
}

void print_response(const SearchRequest& req, const SearchResponse& res, double elapsed_ms,
                    bool explain) {
    std::cout << "query: " << req.query << "\n";
    if (explain) {
        std::cout << "parsed: " << res.parsed << "\n";
    }
    char timing[64];
    std::snprintf(timing, sizeof timing, "%.2f ms", elapsed_ms);
    std::cout << res.total_hits << " matching adverts in " << timing << "\n";
    for (std::size_t i = 0; i < res.hits.size(); ++i) {
        const auto& h = res.hits[i];
        char score[32];
        std::snprintf(score, sizeof score, "%.2f", h.score);
        std::cout << "  " << (req.offset + i + 1) << ". [" << score << "] " << h.job.title << " — "
                  << h.job.company << ", " << h.job.location << " (" << salary_text(h.job) << ", "
                  << contract_name(h.job.contract) << (h.job.remote ? ", remote" : "") << ") "
                  << h.job.id << "\n";
        if (!h.snippet.empty()) {
            std::cout << "     " << h.snippet << "\n";
        }
    }
    if (req.facets && res.total_hits > 0) {
        print_facets("locations", res.locations, 5);
        print_facets("contracts", res.contracts, 3);
        print_facets("salary", res.salary_bands, 5);
    }
}

SortOrder parse_sort(const std::string& s) {
    if (s == "relevance") {
        return SortOrder::Relevance;
    }
    if (s == "newest") {
        return SortOrder::Newest;
    }
    if (s == "salary") {
        return SortOrder::Salary;
    }
    throw SearchError("sort must be relevance, newest or salary");
}

void print_stats(const IndexStats& s) {
    std::cout << "generation " << s.generation << ": " << s.segments << " segments, " << s.live_docs
              << " live adverts, " << s.deleted_docs << " deleted, " << s.buffered_docs
              << " buffered, " << (s.postings_bytes / 1024) << " KiB of postings (" << s.flushes
              << " flushes, " << s.merges << " merges)\n";
}

std::unique_ptr<Index> build_index(std::size_t jobs, std::uint64_t seed) {
    auto index = std::make_unique<Index>();
    const auto t0 = Clock::now();
    const auto corpus = generate_corpus(CorpusOptions{jobs, seed});
    const auto t1 = Clock::now();
    for (const auto& job : corpus) {
        index->upsert(job);
    }
    index->refresh();
    char line[160];
    std::snprintf(line, sizeof line, "generated %zu adverts in %.0f ms, indexed in %.0f ms\n",
                  corpus.size(), std::chrono::duration<double, std::milli>(t1 - t0).count(),
                  ms_since(t1));
    std::cout << line;
    return index;
}

int run(const Args& args) {
    if (args.command == "build") {
        const auto dir = option(args, "dir", "jobs-index");
        auto index = build_index(number(args, "jobs", 100'000), number(args, "seed", 42));
        index->save(dir);
        print_stats(index->stats());
        std::cout << "saved to " << dir << "\n";
        return 0;
    }
    if (args.command == "search") {
        const auto start = Clock::now();
        const auto index = Index::open(option(args, "dir", "jobs-index"));
        const auto opened = ms_since(start);
        SearchRequest req;
        req.query = joined(args.positional);
        req.limit = number(args, "limit", 5);
        req.offset = number(args, "offset", 0);
        req.sort = parse_sort(option(args, "sort", "relevance"));
        req.facets = !args.options.contains("no-facets");
        const auto t = Clock::now();
        const auto res = Searcher(index->snapshot()).search(req);
        print_response(req, res, ms_since(t), args.options.contains("explain"));
        char line[64];
        std::snprintf(line, sizeof line, "(index opened in %.0f ms)\n", opened);
        std::cout << line;
        return 0;
    }
    if (args.command == "close") {
        const auto dir = option(args, "dir", "jobs-index");
        const auto index = Index::open(dir);
        for (const auto& id : args.positional) {
            std::cout << id << (index->remove(id) ? " closed\n" : " not found\n");
        }
        index->save(dir);
        print_stats(index->stats());
        return 0;
    }
    if (args.command == "stats") {
        print_stats(Index::open(option(args, "dir", "jobs-index"))->stats());
        return 0;
    }
    if (args.command == "demo") {
        const auto index = build_index(number(args, "jobs", 20'000), 42);
        print_stats(index->stats());
        const auto request = [](std::string query, std::size_t limit, SortOrder sort) {
            SearchRequest r;
            r.query = std::move(query);
            r.limit = limit;
            r.sort = sort;
            return r;
        };
        const std::vector<SearchRequest> demo{
            request("senior data engineer python", 3, SortOrder::Relevance),
            request("title:nurse location:leeds", 2, SortOrder::Relevance),
            request("\"class 1 licence\" -temporary days:14", 2, SortOrder::Relevance),
            request("(react OR typescript) remote:yes salary>=60k", 3, SortOrder::Salary),
        };
        for (const auto& req : demo) {
            std::cout << "\n";
            const auto t = Clock::now();
            const auto res = Searcher(index->snapshot()).search(req);
            print_response(req, res, ms_since(t), true);
        }
        return 0;
    }
    std::cerr << "usage: jobsearch build|search|close|stats|demo [options]\n";
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        return run(parse_args(argc, argv));
    } catch (const QueryParseError& e) {
        std::cerr << "query error: " << e.what() << "\n";
        return 3;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
