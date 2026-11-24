#include "historian/ingest.hpp"

#include <cmath>
#include <sstream>
#include <string>

#include "historian/analysis.hpp"
#include "historian/simulator.hpp"
#include "support.hpp"

namespace historian {
namespace {

using testing_support::kAlways;
using testing_support::StoreTest;

TEST(Timestamps, ParsesBothFormats) {
    EXPECT_EQ(parse_timestamp("1793577600000"), 1'793'577'600'000);
    EXPECT_EQ(parse_timestamp("2026-11-02T00:00:00Z"), 1'793'577'600'000);
    EXPECT_EQ(parse_timestamp("2026-11-02T00:00:01.250Z"), 1'793'577'601'250);
    EXPECT_EQ(format_timestamp(1'793'577'601'250), "2026-11-02T00:00:01.250Z");
}

class BadTimestamp : public ::testing::TestWithParam<const char*> {};
TEST_P(BadTimestamp, IsRejected) { EXPECT_FALSE(parse_timestamp(GetParam()).has_value()); }
INSTANTIATE_TEST_SUITE_P(Cases, BadTimestamp,
                         ::testing::Values("", "0", "4070908800000", "2026-02-30T00:00:00Z",
                                           "2026-11-02T24:00:00Z", "2026-11-02 00:00:00Z",
                                           "2026-11-02T00:00:00", "2026-11-02T00:00:00+01:00",
                                           "2026-11-02T00:00:00.5Z", "2026-+1-02T00:00:00Z"));

struct LineCase {
    const char* text;
    RejectReason reason;
};
class BadLine : public ::testing::TestWithParam<LineCase> {};
TEST_P(BadLine, HasTheRightReason) {
    const auto parsed = parse_line(GetParam().text);
    ASSERT_TRUE(std::holds_alternative<RejectReason>(parsed));
    EXPECT_EQ(std::get<RejectReason>(parsed), GetParam().reason);
}
INSTANTIATE_TEST_SUITE_P(
    Cases, BadLine,
    ::testing::Values(LineCase{"", RejectReason::FieldCount},
                      LineCase{"1793577600000,press-01,temp_c", RejectReason::FieldCount},
                      LineCase{"1793577600000,press-01,temp_c,1,2", RejectReason::FieldCount},
                      LineCase{"yesterday,press-01,temp_c,1", RejectReason::BadTimestamp},
                      LineCase{"1793577600000,Press 1,temp_c,1", RejectReason::BadMachine},
                      LineCase{"1793577600000,press-01,humidity,1", RejectReason::UnknownSensor},
                      LineCase{"1793577600000,press-01,temp_c,nan", RejectReason::BadValue},
                      LineCase{"1793577600000,press-01,temp_c,0x10", RejectReason::BadValue},
                      LineCase{"1793577600000,press-01,temp_c,", RejectReason::BadValue},
                      LineCase{"1793577600000,press-01,temp_c,400.1", RejectReason::OutOfRange}));

TEST(ParseLine, TrimsWhitespaceAndCarriageReturn) {
    const auto parsed = parse_line("1793577600000, press-01 ,temp_c, 61.5\r");
    ASSERT_TRUE(std::holds_alternative<Point>(parsed));
    EXPECT_EQ(std::get<Point>(parsed).series, "press-01/temp_c");
    EXPECT_EQ(std::get<Point>(parsed).sample.value, 61.5);
}

TEST_F(StoreTest, IngestQuarantinesWithLineNumbers) {
    auto store = open(db());
    std::istringstream in(
        "timestamp,machine,sensor,value\n"
        "1793577600000,press-01,temp_c,61.5\n"
        "garbage\n"
        "1793577601000,press-01,temp_c,9999\n");
    std::ostringstream quarantine;
    const auto report = ingest_csv(in, *store, quarantine).value();
    EXPECT_EQ(report.accepted, 1U);
    EXPECT_EQ(report.rejected, 2U);
    EXPECT_EQ(quarantine.str(),
              "3,field_count,garbage\n4,out_of_range,1793577601000,press-01,temp_c,9999\n");
}

TEST_F(StoreTest, LaterLinesWinWhateverTheParserScheduling) {
    auto store = open(db());
    std::string text;
    for (int i = 0; i < 5000; ++i) {
        text += "1793577600000,press-01,part_count," + std::to_string(i) + "\n";
    }
    std::istringstream in(text);
    std::ostringstream quarantine;
    const IngestOptions options{.parsers = 8, .batch_lines = 7, .max_in_flight = 5};
    ASSERT_TRUE(ingest_csv(in, *store, quarantine, options).ok());
    const auto samples = store->scan("press-01/part_count", 0, kAlways).value();
    ASSERT_EQ(samples.size(), 1U);
    EXPECT_EQ(samples[0].value, 4999.0);
}

TEST_F(StoreTest, IngestRejectsZeroThreads) {
    auto store = open(db());
    std::istringstream in;
    std::ostringstream quarantine;
    EXPECT_FALSE(ingest_csv(in, *store, quarantine, {.parsers = 0}).ok());
}

TEST_F(StoreTest, StorageFailureStopsThePipelineWithoutDeadlock) {
    auto store = open(db(), 1000);  // the first flush will fail
    std::filesystem::remove_all(db());
    std::string text;
    for (int i = 0; i < 20'000; ++i) {
        text += std::to_string(1'793'577'600'000 + i) + ",press-01,temp_c,60\n";
    }
    std::istringstream in(text);
    std::ostringstream quarantine;
    const IngestOptions options{.parsers = 3, .batch_lines = 100, .max_in_flight = 4};
    const auto report = ingest_csv(in, *store, quarantine, options);
    ASSERT_FALSE(report.ok());
    EXPECT_EQ(report.error().code, ErrorCode::Io);
}

TEST_F(StoreTest, SimulatedPlantEndToEnd) {
    std::stringstream csv;
    const auto simulated = simulate(csv, {.machines = 4, .seconds = 1200});
    auto store = open(db(), 5000);
    std::ostringstream quarantine;
    const auto report = ingest_csv(csv, *store, quarantine).value();
    EXPECT_EQ(report.lines, simulated.lines);
    EXPECT_EQ(report.rejected, simulated.corrupted);
    EXPECT_EQ(store->series().size(), 24U);
    std::uint64_t stored = 0;
    for (const auto& name : store->series()) {
        stored += store->scan(name, 0, kAlways).value().size();
    }
    EXPECT_EQ(stored, 4U * 1200U * 6U - simulated.dropped);  // duplicates collapse, late kept
    ASSERT_TRUE(store->compact({.full = true, .expire_before = {}}).ok());
    ASSERT_TRUE(store->verify().ok());
}

TEST(Simulator, IsDeterministicPerSeed) {
    std::ostringstream a;
    std::ostringstream b;
    std::ostringstream c;
    static_cast<void>(simulate(a, {.machines = 2, .seconds = 100}));
    static_cast<void>(simulate(b, {.machines = 2, .seconds = 100}));
    static_cast<void>(simulate(c, {.machines = 2, .seconds = 100, .seed = 43}));
    EXPECT_EQ(a.str(), b.str());
    EXPECT_NE(a.str(), c.str());
}

TEST(Analysis, GapsNeedStrictlyMoreThanTheLimit) {
    const std::vector<Sample> samples{{0, 0}, {1000, 0}, {3000, 0}, {9000, 0}};
    const auto gaps = find_gaps(samples, 2000);
    ASSERT_EQ(gaps.size(), 1U);
    EXPECT_EQ(gaps[0].from, 3000);
    EXPECT_EQ(gaps[0].to, 9000);
}

TEST(Analysis, HysteresisPreventsAlarmChatter) {
    const std::vector<Sample> samples{{0, 79}, {1, 81}, {2, 79}, {3, 85},
                                      {4, 76}, {5, 74}, {6, 90}};
    const auto with =
        find_excursions(samples, {.trip = 80, .reset = 75, .min_duration = 0, .max_gap = 10});
    ASSERT_EQ(with.size(), 2U);
    EXPECT_EQ(with[0].from, 1);
    EXPECT_EQ(with[0].to, 4);
    EXPECT_EQ(with[0].peak, 85.0);
    const auto without =
        find_excursions(samples, {.trip = 80, .reset = 80, .min_duration = 0, .max_gap = 10});
    EXPECT_EQ(without.size(), 3U);
}

TEST(Analysis, ShortExcursionsAndSilencesAreHandled) {
    const std::vector<Sample> samples{{0, 90}, {5, 90}, {1000, 90}, {1100, 90}};
    const auto found =
        find_excursions(samples, {.trip = 80, .reset = 80, .min_duration = 50, .max_gap = 200});
    ASSERT_EQ(found.size(), 1U);  // the silence splits it; the first part is too short
    EXPECT_EQ(found[0].from, 1000);
}

TEST(Analysis, TimeWeightedMeanIgnoresSamplingRate) {
    // 10 for nine seconds, then 100 reported ten times within one second.
    std::vector<Sample> samples{{0, 10}};
    for (int i = 0; i <= 10; ++i) {
        samples.push_back({9000 + i * 100, 100});
    }
    EXPECT_NEAR(time_weighted_mean(samples, 60'000), 19.0, 1e-9);
    EXPECT_TRUE(std::isnan(time_weighted_mean({}, 1)));
    EXPECT_EQ(time_weighted_mean(std::vector<Sample>{{1, 5.0}}, 1), 5.0);
}

}  // namespace
}  // namespace historian
