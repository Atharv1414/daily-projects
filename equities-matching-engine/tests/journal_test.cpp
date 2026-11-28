#include "lob/journal.hpp"

#include <gtest/gtest.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>

#include "lob/exchange.hpp"
#include "lob/order_flow.hpp"

namespace lob {
namespace {

std::string sample_journal() {
    std::string text;
    text +=
        journal_record(1, parse_command("NEW sym=TGX id=1 owner=1 side=B px=1000 qty=100").value());
    text +=
        journal_record(2, parse_command("NEW sym=TGX id=2 owner=2 side=S px=1000 qty=40").value());
    text += journal_record(3, parse_command("CXL sym=TGX id=1").value());
    return text;
}

TEST(Journal, Crc32MatchesKnownVector) {
    EXPECT_EQ(crc32("123456789"), 0xCBF4'3926u);  // the standard CRC-32 check value
}

TEST(Journal, ReadsBackEveryRecord) {
    auto r = read_journal_text(sample_journal());
    ASSERT_TRUE(r) << r.error();
    EXPECT_EQ(r.value().commands.size(), 3u);
    EXPECT_EQ(r.value().last_seq, 3u);
    EXPECT_EQ(r.value().torn_tail_bytes, 0u);
}

TEST(Journal, DropsTornTailFromACrash) {
    std::string text = sample_journal();
    text += "4|NEW sym=TGX id=9 owner=1 si";  // write cut off mid-record
    auto r = read_journal_text(text);
    ASSERT_TRUE(r) << r.error();
    EXPECT_EQ(r.value().commands.size(), 3u);
    EXPECT_EQ(r.value().torn_tail_bytes, 29u);
}

TEST(Journal, RefusesCorruptionInTheMiddle) {
    std::string text = sample_journal();
    text[text.find("qty=40") + 4] = '9';  // flip one digit: 40 -> 90
    auto r = read_journal_text(text);
    ASSERT_FALSE(r);
    EXPECT_NE(r.error().find("checksum mismatch at record 2"), std::string::npos) << r.error();
}

TEST(Journal, RefusesSequenceGaps) {
    std::string text = journal_record(1, parse_command("CXL sym=TGX id=1").value());
    text += journal_record(3, parse_command("CXL sym=TGX id=2").value());
    auto r = read_journal_text(text);
    ASSERT_FALSE(r);
    EXPECT_NE(r.error().find("sequence gap"), std::string::npos);
}

TEST(Journal, ReplayRebuildsIdenticalState) {
    const auto path = std::filesystem::temp_directory_path() / "tmatch_replay_test.journal";
    std::filesystem::remove(path);
    FlowProfile profile;
    BookConfig cfg;
    cfg.symbol = profile.symbol;
    cfg.reference_price = profile.start_mid;

    std::uint64_t live_hash = 0;
    {
        Exchange live;
        live.list(cfg);
        live.attach_journal(std::make_unique<JournalWriter>(path));
        for (const Command& c : generate_session(profile, 5, 20'000, cfg)) (void)live.apply(c);
        live_hash = live.state_hash();
    }  // journal flushed and closed here

    Exchange rebuilt;
    rebuilt.list(cfg);
    auto replayed = replay(rebuilt, path);
    ASSERT_TRUE(replayed) << replayed.error();
    EXPECT_EQ(replayed.value(), 20'000u);
    EXPECT_EQ(rebuilt.state_hash(), live_hash);
    EXPECT_EQ(rebuilt.market_data(profile.symbol)->stats().volume > 0, true);
    std::filesystem::remove(path);
}

}  // namespace
}  // namespace lob
