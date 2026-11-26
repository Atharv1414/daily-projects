#include "jobsearch/query.hpp"

#include <gtest/gtest.h>

using namespace jobsearch;

struct ParseCase {
    const char* input;
    const char* expected;
};

class ParseTest : public ::testing::TestWithParam<ParseCase> {};

TEST_P(ParseTest, ProducesCanonicalTree) {
    EXPECT_EQ(to_string(*parse_query(GetParam().input)), GetParam().expected) << GetParam().input;
}

INSTANTIATE_TEST_SUITE_P(
    Grammar, ParseTest,
    ::testing::Values(ParseCase{"", "*"}, ParseCase{"Engineers", "engineer"},
                      ParseCase{"data engineer", "(AND data engineer)"},
                      ParseCase{"data AND engineer", "(AND data engineer)"},
                      ParseCase{"python OR scala", "(OR python scala)"},
                      ParseCase{"data engineer OR analyst", "(OR (AND data engineer) analyst)"},
                      ParseCase{"nurse -agency", "(AND nurs (NOT agency))"},
                      ParseCase{"nurse NOT agency", "(AND nurs (NOT agency))"},
                      ParseCase{"\"head of data\"", "\"head@0 data@2\""},
                      ParseCase{"title:\"Band 6\"", "title:\"band@0 6@1\""},
                      ParseCase{"title:Nurses", "title:nurs"}, ParseCase{"engin*", "engin*"},
                      ParseCase{"front-end", "\"front@0 end@1\""},
                      ParseCase{"(python OR go) -junior", "(AND (OR python go) (NOT junior))"},
                      ParseCase{"a (b c)", "(AND b c)"},  // "a" is a stop word; nested AND flattens
                      ParseCase{"salary>=45000", "[salary>=45000]"},
                      ParseCase{"salary>=45k", "[salary>=45000]"},
                      ParseCase{"salary>=\xC2\xA3"
                                "50,000",
                                "[salary>=50000]"},
                      ParseCase{
                          "location:Leeds contract:perm remote:yes days:7",
                          "(AND [location=leeds] [contract=permanent] [remote=yes] [days<=7])"},
                      ParseCase{"c++ OR c#", "(OR c++ c#)"}));

struct ErrorCase {
    const char* input;
    std::size_t position;
};

class ParseErrorTest : public ::testing::TestWithParam<ErrorCase> {};

TEST_P(ParseErrorTest, ReportsPosition) {
    try {
        (void)parse_query(GetParam().input);
        FAIL() << "expected a parse error for " << GetParam().input;
    } catch (const QueryParseError& e) {
        EXPECT_EQ(e.position(), GetParam().position) << e.what();
    }
}

INSTANTIATE_TEST_SUITE_P(Errors, ParseErrorTest,
                         ::testing::Values(ErrorCase{"\"unclosed phrase", 0},
                                           ErrorCase{"(python", 0}, ErrorCase{"python)", 6},
                                           ErrorCase{"python OR", 7}, ErrorCase{"nurse -", 6},
                                           ErrorCase{"colour:blue", 0},
                                           ErrorCase{"salary>=lots", 0}, ErrorCase{"e*", 0},
                                           ErrorCase{"()", 0}, ErrorCase{"remote:maybe", 0},
                                           ErrorCase{"the and of", 0}));

TEST(Parse, EnforcesLimits) {
    ParseLimits limits;
    limits.max_clauses = 3;
    EXPECT_NO_THROW((void)parse_query("a1 b2 c3", limits));
    EXPECT_THROW((void)parse_query("a1 b2 c3 d4", limits), QueryParseError);
    EXPECT_THROW((void)parse_query(std::string(2000, 'x')), QueryParseError);
    EXPECT_THROW((void)parse_query(std::string(40, '(') + "x" + std::string(40, ')')),
                 QueryParseError);
}

TEST(Parse, HighlightTermsSkipExclusionsAndMarkPrefixes) {
    const auto q = parse_query("senior engin* -recruiter \"data platform\"");
    const std::vector<std::string> expected{"data", "engin*", "platform", "senior"};
    EXPECT_EQ(highlight_terms(*q), expected);
}
