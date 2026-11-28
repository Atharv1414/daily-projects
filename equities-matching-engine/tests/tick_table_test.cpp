#include "lob/tick_table.hpp"

#include <gtest/gtest.h>

#include <stdexcept>

#include "lob/command.hpp"

namespace lob {
namespace {

struct TickCase {
    Price price;
    Price tick;
};

class UkTicks : public ::testing::TestWithParam<TickCase> {};

TEST_P(UkTicks, BandBoundaries) {
    const TickTable t = TickTable::uk_liquid();
    EXPECT_EQ(t.tick_for(GetParam().price), GetParam().tick);
}

INSTANTIATE_TEST_SUITE_P(Bands, UkTicks,
                         ::testing::Values(TickCase{1, 1}, TickCase{9'999, 1}, TickCase{10'000, 5},
                                           TickCase{49'995, 5}, TickCase{50'000, 10},
                                           TickCase{99'990, 10}, TickCase{100'000, 50},
                                           TickCase{499'950, 50}, TickCase{500'000, 100},
                                           TickCase{9'999'900, 100}));

TEST(TickTable, ValidatesAndRounds) {
    const TickTable t = TickTable::uk_liquid();
    EXPECT_TRUE(t.is_valid(123'450));   // 1234.50p on a 0.5p tick
    EXPECT_FALSE(t.is_valid(123'455));  // 1234.55p is not
    EXPECT_FALSE(t.is_valid(0));
    EXPECT_FALSE(t.is_valid(-50));
    EXPECT_EQ(t.round_down(123'499), 123'450);
    EXPECT_EQ(t.next_up(123'450), 123'500);
}

TEST(TickTable, RejectsMalformedTables) {
    EXPECT_THROW(TickTable({}), std::invalid_argument);
    EXPECT_THROW(TickTable({{100, 0}}), std::invalid_argument);
    EXPECT_THROW(TickTable({{100, 1}, {50, 1}}), std::invalid_argument);
    EXPECT_THROW(TickTable({{105, 1}, {200, 10}}), std::invalid_argument);  // 105 not on 10
}

TEST(Price, ParsesAndFormatsPence) {
    EXPECT_EQ(parse_price("1234.5").value(), 123'450);
    EXPECT_EQ(parse_price("1234.05").value(), 123'405);
    EXPECT_EQ(parse_price("7").value(), 700);
    EXPECT_FALSE(parse_price("12.345"));
    EXPECT_FALSE(parse_price("-1"));
    EXPECT_FALSE(parse_price("abc"));
    EXPECT_FALSE(parse_price("1."));
    EXPECT_EQ(format_price(123'405), "1234.05p");
    EXPECT_EQ(format_price(5), "0.05p");
}

}  // namespace
}  // namespace lob
