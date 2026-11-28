#include "lob/command.hpp"

#include <gtest/gtest.h>

#include <string>

#include "lob/order_flow.hpp"

namespace lob {
namespace {

TEST(Command, ParsesFullNewOrder) {
    auto r = parse_command(
        "NEW sym=TGX id=17 owner=3 side=S type=ICE tif=DAY px=1234.5 qty=5000 peak=500 post=1 "
        "stp=CI");
    ASSERT_TRUE(r) << r.error();
    const auto& s = std::get<SubmitCmd>(r.value());
    EXPECT_EQ(s.symbol, "TGX");
    EXPECT_EQ(s.order.id, 17u);
    EXPECT_EQ(s.order.side, Side::Sell);
    EXPECT_EQ(s.order.type, OrderType::Iceberg);
    EXPECT_EQ(s.order.price, 123'450);
    EXPECT_EQ(s.order.display_qty, 500);
    EXPECT_TRUE(s.order.post_only);
    EXPECT_EQ(s.order.stp, StpMode::CancelIncoming);
}

TEST(Command, DefaultsToDayLimitWithCancelResting) {
    auto r = parse_command("NEW sym=TGX id=1 owner=1 side=B px=10 qty=1");
    ASSERT_TRUE(r);
    const auto& o = std::get<SubmitCmd>(r.value()).order;
    EXPECT_EQ(o.type, OrderType::Limit);
    EXPECT_EQ(o.tif, TimeInForce::Day);
    EXPECT_EQ(o.stp, StpMode::CancelResting);
    EXPECT_EQ(o.price, 1'000);
}

struct BadLine {
    const char* line;
    const char* fragment;
};

class CommandErrors : public ::testing::TestWithParam<BadLine> {};

TEST_P(CommandErrors, ExplainsWhatIsWrong) {
    auto r = parse_command(GetParam().line);
    ASSERT_FALSE(r) << GetParam().line;
    EXPECT_NE(r.error().find(GetParam().fragment), std::string::npos) << r.error();
}

INSTANTIATE_TEST_SUITE_P(
    Cases, CommandErrors,
    ::testing::Values(
        BadLine{"", "empty"}, BadLine{"FOO sym=TGX", "unknown command"},
        BadLine{"NEW id=1 owner=1 side=B px=1 qty=1", "missing sym"},
        BadLine{"NEW sym=TGX id=1 owner=1 side=X px=1 qty=1", "side must be"},
        BadLine{"NEW sym=TGX id=1 owner=1 side=B px=1.234 qty=1", "decimals"},
        BadLine{"NEW sym=TGX id=1 owner=1 side=B px=1 qty=ten", "bad number"},
        BadLine{"NEW sym=TGX id=1 owner=1 side=B px=1 qty=1 colour=red", "unknown field"},
        BadLine{"NEW sym=TGX id=1 id=2 owner=1 side=B px=1 qty=1", "repeated"},
        BadLine{"NEW sym=TGX id=1 owner=1 side=B type=MKT px=1 qty=1", "market orders take no px"},
        BadLine{"CXL sym=TGX", "missing id"}));

TEST(Command, FormatParseRoundTripOverGeneratedFlow) {
    OrderFlowGenerator gen(FlowProfile{}, 11);
    for (int i = 0; i < 5'000; ++i) {
        const Command c = gen.next();
        const std::string text = format_command(c);
        auto back = parse_command(text);
        ASSERT_TRUE(back) << text << ": " << back.error();
        EXPECT_EQ(format_command(back.value()), text);
    }
}

TEST(Command, SessionCommandsRoundTrip) {
    for (const char* line :
         {"AUCTION sym=TGX", "UNCROSS sym=TGX", "HALT sym=TGX", "RESUME sym=TGX"}) {
        auto r = parse_command(line);
        ASSERT_TRUE(r);
        EXPECT_EQ(format_command(r.value()), line);
    }
}

}  // namespace
}  // namespace lob
