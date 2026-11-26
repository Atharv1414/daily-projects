#include "jobsearch/searcher.hpp"

#include <gtest/gtest.h>

#include <algorithm>
#include <set>

#include "jobsearch/corpus.hpp"
#include "jobsearch/index.hpp"
#include "jobsearch/text.hpp"
#include "support.hpp"

using namespace jobsearch;
using jobsearch::testing::job;

namespace {

class SearcherTest : public ::testing::Test {
  protected:
    void SetUp() override {
        add(job("title-hit", "Data Engineer", "Build pipelines with Spark", "Leeds", 60'000, 30));
        add(job("body-hit", "Software Developer",
                "Work alongside a data engineer and analysts on Spark jobs", "London", 70'000, 28));
        add(job("analyst", "Data Analyst", "SQL and Power BI reporting for the data team",
                "Manchester", 38'000, 29));
        add(job("phrase", "Head of Data", "Lead the data platform team", "London", 95'000, 5));
        add(job("not-phrase", "Data Lead", "Head office role leading data quality", "Leeds", 55'000,
                25));
        add(job("nurse", "Registered Nurse", "Band 5 ward nurse, NHS", "Leeds", 33'000, 30));
        JobAd remote =
            job("remote", "Front-End Developer", "React and TypeScript", "Remote", 65'000, 30);
        remote.remote = true;
        remote.contract = Contract::Contract;
        add(remote);
        index.refresh();
    }

    void add(JobAd j) { index.upsert(std::move(j)); }

    SearchResponse run(const std::string& q, std::size_t limit = 10,
                       SortOrder sort = SortOrder::Relevance) const {
        SearchRequest req;
        req.query = q;
        req.limit = limit;
        req.sort = sort;
        return Searcher(index.snapshot()).search(req);
    }

    static std::set<std::string> ids(const SearchResponse& r) {
        std::set<std::string> out;
        for (const auto& h : r.hits) {
            out.insert(h.job.id);
        }
        return out;
    }

    Index index;
};

}  // namespace

TEST_F(SearcherTest, TitleMatchOutranksBodyMention) {
    const auto r = run("data engineer");
    ASSERT_GE(r.hits.size(), 2U);
    EXPECT_EQ(r.hits[0].job.id, "title-hit");
    EXPECT_TRUE(ids(r).contains("body-hit"));
    EXPECT_GT(r.hits[0].score, r.hits[1].score);
}

TEST_F(SearcherTest, PhraseRequiresAdjacencyAcrossStopWords) {
    const auto r = run("\"head of data\"");
    EXPECT_EQ(ids(r), (std::set<std::string>{"phrase"}));
    // The same words without quotes also match the advert that only has them apart.
    EXPECT_TRUE(ids(run("head data")).contains("not-phrase"));
}

TEST_F(SearcherTest, OrUnionsAndNotExcludes) {
    EXPECT_EQ(ids(run("nurse OR react")), (std::set<std::string>{"nurse", "remote"}));
    const auto r = run("data -spark");
    EXPECT_FALSE(ids(r).contains("title-hit"));
    EXPECT_FALSE(ids(r).contains("body-hit"));
    EXPECT_TRUE(ids(r).contains("analyst"));
    EXPECT_EQ(run("-data").total_hits, 2U);  // pure negation means "everything except"
}

TEST_F(SearcherTest, FieldRestrictionLimitsToTitle) {
    EXPECT_EQ(ids(run("title:engineer")), (std::set<std::string>{"title-hit"}));
    EXPECT_EQ(ids(run("body:engineer")), (std::set<std::string>{"body-hit"}));
}

TEST_F(SearcherTest, PrefixMatchesStemmedVocabulary) {
    EXPECT_EQ(ids(run("title:engin*")), (std::set<std::string>{"title-hit"}));
    EXPECT_EQ(run("analy*").total_hits, 2U);  // "analyst" title, "analysts" body
}

TEST_F(SearcherTest, FiltersCombineWithText) {
    EXPECT_EQ(ids(run("data location:leeds")), (std::set<std::string>{"title-hit", "not-phrase"}));
    EXPECT_EQ(ids(run("salary>=90k")), (std::set<std::string>{"phrase"}));
    EXPECT_EQ(ids(run("remote:yes contract:contract")), (std::set<std::string>{"remote"}));
    EXPECT_EQ(run("days:2").total_hits, 5U);  // posted on day 28..30 when today = 30
    EXPECT_EQ(run("location:atlantis").total_hits, 0U);
}

TEST_F(SearcherTest, SortOrdersAreTotalAndStable) {
    const auto by_salary = run("", 3, SortOrder::Salary);
    ASSERT_EQ(by_salary.hits.size(), 3U);
    EXPECT_EQ(by_salary.hits[0].job.id, "phrase");
    EXPECT_EQ(by_salary.hits[1].job.id, "body-hit");
    const auto newest = run("", 10, SortOrder::Newest);
    for (std::size_t i = 1; i < newest.hits.size(); ++i) {
        EXPECT_GE(newest.hits[i - 1].job.posted_day, newest.hits[i].job.posted_day);
    }
}

TEST_F(SearcherTest, FacetsCountAllMatchesNotJustThePage) {
    const auto r = run("", 1);
    EXPECT_EQ(r.hits.size(), 1U);
    ASSERT_FALSE(r.locations.empty());
    EXPECT_EQ(r.locations[0], (FacetCount{"Leeds", 3}));
    std::uint64_t total = 0;
    for (const auto& f : r.salary_bands) {
        total += f.count;
    }
    EXPECT_EQ(total, 7U);
}

TEST_F(SearcherTest, SnippetHighlightsMatchedWords) {
    const auto r = run("spark pipelines");
    ASSERT_FALSE(r.hits.empty());
    EXPECT_EQ(r.hits[0].snippet, "Build [pipelines] with [Spark]");
}

TEST_F(SearcherTest, ValidatesPaging) {
    SearchRequest req;
    req.limit = 0;
    EXPECT_THROW((void)Searcher(index.snapshot()).search(req), SearchError);
    req.limit = 101;
    EXPECT_THROW((void)Searcher(index.snapshot()).search(req), SearchError);
    req.limit = 10;
    req.offset = 50;
    EXPECT_TRUE(Searcher(index.snapshot()).search(req).hits.empty());
}

TEST(Searcher, PagesNeverOverlapOrSkip) {
    Index index;
    for (const auto& j : generate_corpus(CorpusOptions{3'000, 9})) {
        index.upsert(j);
    }
    index.refresh();
    const Searcher searcher(index.snapshot());
    SearchRequest req;
    req.query = "engineer OR analyst";
    req.limit = 25;
    req.facets = false;
    req.snippets = false;
    const auto total = searcher.search(req).total_hits;
    std::set<std::string> seen;
    for (req.offset = 0; req.offset < total; req.offset += req.limit) {
        for (const auto& h : searcher.search(req).hits) {
            EXPECT_TRUE(seen.insert(h.job.id).second) << "duplicate " << h.job.id;
        }
    }
    EXPECT_EQ(seen.size(), total);
}

TEST(Searcher, IdfIsGlobalAcrossSegments) {
    // The same document must score the same whether the index has one segment or many.
    const auto corpus = generate_corpus(CorpusOptions{800, 13});
    IndexOptions many;
    many.flush_threshold = 100;
    many.max_segments = 100;
    Index split(many);
    Index single;
    for (const auto& j : corpus) {
        split.upsert(j);
        single.upsert(j);
    }
    split.refresh();
    single.force_merge();
    ASSERT_GT(split.stats().segments, 5U);
    SearchRequest req;
    req.query = "senior python";
    req.limit = 5;
    const auto a = Searcher(split.snapshot()).search(req);
    const auto b = Searcher(single.snapshot()).search(req);
    ASSERT_EQ(a.total_hits, b.total_hits);
    for (std::size_t i = 0; i < a.hits.size(); ++i) {
        EXPECT_EQ(a.hits[i].job.id, b.hits[i].job.id);
        EXPECT_NEAR(a.hits[i].score, b.hits[i].score, 1e-9);
    }
}

TEST(Searcher, BruteForceAgreesOnCorpusConjunctions) {
    // Cross-check the inverted index against a naive scan of the analysed text.
    const auto corpus = generate_corpus(CorpusOptions{1'500, 17});
    Index index;
    for (const auto& j : corpus) {
        index.upsert(j);
    }
    index.refresh();
    const std::vector<std::pair<std::string, std::vector<std::string>>> queries{
        {"python sql", {"python", "sql"}},
        {"forklift shift", {"forklift", "shift"}},
        {"senior nurse", {"senior", "nurse"}}};
    for (const auto& [query, terms] : queries) {
        std::uint64_t expected = 0;
        for (const auto& j : corpus) {
            const auto text = analyze(j.title + " " + j.body);
            const bool all = std::ranges::all_of(terms, [&](const std::string& t) {
                return std::ranges::any_of(
                    text, [&](const Token& tok) { return tok.term == normalize_term(t); });
            });
            expected += (all) ? 1U : 0U;
        }
        SearchRequest req;
        req.query = query;
        EXPECT_EQ(Searcher(index.snapshot()).search(req).total_hits, expected) << query;
    }
}

TEST(Snippet, CentresOnDensestWindowWithEllipses) {
    const std::string text =
        "Intro words here. Lots of filler text about nothing in particular at all, "
        "and then finally the Kafka and Spark pipeline appears near the end";
    const auto s = make_snippet(text, {"kafka", "spark"}, 6);
    EXPECT_EQ(s, "… then finally the [Kafka] and [Spark] …");
    EXPECT_EQ(make_snippet("", {"x"}), "");
}
