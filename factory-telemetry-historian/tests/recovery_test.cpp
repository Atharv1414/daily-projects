#include <algorithm>
#include <fstream>
#include <iterator>

#include "historian/file.hpp"
#include "support.hpp"

namespace historian {
namespace {

namespace fs = std::filesystem;
using testing_support::kAlways;
using testing_support::points;
using testing_support::StoreTest;

fs::path find_file(const fs::path& directory, const std::string& prefix) {
    for (const auto& entry : fs::directory_iterator(directory)) {
        if (entry.path().filename().string().starts_with(prefix)) {
            return entry.path();
        }
    }
    return {};
}

void write_bytes(const fs::path& path, const std::vector<std::uint8_t>& bytes) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    std::ranges::transform(bytes, std::ostreambuf_iterator<char>(out),
                           [](std::uint8_t b) { return static_cast<char>(b); });
}

class RecoveryTest : public StoreTest {
  protected:
    /// Copies the live files, as if the process had died at this instant.
    fs::path crash_copy(const std::string& name) {
        const auto target = directory() / name;
        fs::remove_all(target);
        fs::copy(db(), target, fs::copy_options::recursive);
        return target;
    }
};

TEST_F(RecoveryTest, UnflushedBatchesSurviveACrash) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 0, 500)).ok());
    auto recovered = open(crash_copy("crashed"));
    EXPECT_EQ(recovered->recovery().samples_replayed, 500U);
    EXPECT_FALSE(recovered->recovery().torn_tail);
    EXPECT_EQ(recovered->scan("m/a", 0, kAlways).value(), store->scan("m/a", 0, kAlways).value());
}

TEST_F(RecoveryTest, TornWalAtEveryByteRecoversAWholeBatchPrefix) {
    auto store = open(db());
    for (int i = 0; i < 4; ++i) {
        ASSERT_TRUE(store->append(points("m/a", i * 10, 10)).ok());
    }
    const auto wal = find_file(db(), "wal-").filename();
    const auto bytes = read_file(db() / wal).value();
    for (std::size_t n = 0; n <= bytes.size(); ++n) {
        const auto copy = crash_copy("torn");
        write_bytes(copy / wal, {bytes.begin(), bytes.begin() + static_cast<std::ptrdiff_t>(n)});
        auto recovered = open(copy);
        ASSERT_NE(recovered, nullptr);
        const auto samples = recovered->scan("m/a", 0, kAlways).value();
        EXPECT_EQ(samples.size(), n / (bytes.size() / 4) * 10) << "truncated to " << n;
        EXPECT_EQ(recovered->recovery().torn_tail, n % (bytes.size() / 4) != 0);
    }
}

TEST_F(RecoveryTest, BitFlipInWalIsDetected) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 0, 10)).ok());
    ASSERT_TRUE(store->append(points("m/a", 10, 10)).ok());
    const auto copy = crash_copy("flipped");
    const auto wal = find_file(copy, "wal-");
    auto bytes = read_file(wal).value();
    bytes[bytes.size() - 5] ^= 0x10U;
    write_bytes(wal, bytes);
    auto recovered = open(copy);
    EXPECT_TRUE(recovered->recovery().torn_tail);
    EXPECT_EQ(recovered->scan("m/a", 0, kAlways).value().size(), 10U);
}

TEST_F(RecoveryTest, RecoveryIsIdempotentWhenItCrashesBeforeCommitting) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 0, 10)).ok());
    ASSERT_TRUE(store->append(points("m/a", 10, 10)).ok());
    const auto copy = crash_copy("half");
    const auto wal = find_file(copy, "wal-");
    auto bytes = read_file(wal).value();
    bytes.resize(bytes.size() - 3);
    write_bytes(wal, bytes);
    // The first recovery wrote a segment and a new WAL, then died before the manifest rename.
    write_bytes(copy / "seg-90.hsg", {1, 2, 3});
    write_bytes(copy / "wal-91.log", {});
    auto recovered = open(copy);
    ASSERT_NE(recovered, nullptr);
    EXPECT_EQ(recovered->scan("m/a", 0, kAlways).value().size(), 10U);
    EXPECT_EQ(recovered->recovery().orphans_removed, 1U);
}

TEST_F(RecoveryTest, DamageBeforeAcknowledgedBatchesIsAnError) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 0, 10)).ok());
    const auto copy = crash_copy("damaged");
    const auto wal = find_file(copy, "wal-");
    const auto good = read_file(wal).value();
    write_bytes(copy / "wal-50.log", good);
    auto bad = good;
    bad[12] ^= 0xFFU;
    write_bytes(wal, bad);
    const auto result = Store::open(copy);
    ASSERT_FALSE(result.ok());
    EXPECT_EQ(result.error().code, ErrorCode::Corrupt);
}

TEST_F(RecoveryTest, StaleWalBelowTheFloorIsNotReplayed) {
    auto store = open(db());
    ASSERT_TRUE(store->append(points("m/a", 0, 10, 1.0)).ok());
    const auto old_wal = find_file(db(), "wal-");
    const auto old_bytes = read_file(old_wal).value();
    ASSERT_TRUE(store->flush().ok());
    ASSERT_TRUE(store->append(points("m/a", 0, 10, 7.0)).ok());
    const auto copy = crash_copy("stale");
    write_bytes(copy / old_wal.filename(), old_bytes);  // unlink never reached the disk
    auto recovered = open(copy);
    EXPECT_EQ(recovered->scan("m/a", 0, kAlways).value().front().value, 7.0);
    EXPECT_EQ(recovered->recovery().orphans_removed, 1U);
}

TEST_F(RecoveryTest, CrashBetweenCompactionOutputAndManifestKeepsInputs) {
    auto store = open(db());
    for (int i = 0; i < 2; ++i) {
        ASSERT_TRUE(store->append(points("m/a", i * 10, 10)).ok());
        ASSERT_TRUE(store->flush().ok());
    }
    const auto copy = crash_copy("compacting");
    write_bytes(copy / "seg-77.hsg", {0, 0, 0});
    write_bytes(copy / "MANIFEST.tmp", {0});
    auto recovered = open(copy);
    EXPECT_EQ(recovered->scan("m/a", 0, kAlways).value().size(), 20U);
    EXPECT_EQ(recovered->recovery().orphans_removed, 2U);
}

TEST_F(RecoveryTest, EveryFlippedSegmentByteIsCaughtOnOpenOrVerify) {
    {
        auto store = open(db());
        ASSERT_TRUE(store->append(points("m/a", 0, 200)).ok());
        ASSERT_TRUE(store->flush().ok());
    }
    const auto name = find_file(db(), "seg-").filename();
    const auto good = read_file(db() / name).value();
    // Byte 0-3 is the leading magic, which is informational only.
    for (std::size_t i = 4; i < good.size(); ++i) {
        auto bad = good;
        bad[i] ^= 0x01U;
        write_bytes(db() / name, bad);
        const auto store = Store::open(db());
        const bool caught = !store.ok() || !store.value()->verify().ok();
        EXPECT_TRUE(caught) << "byte " << i;
    }
}

TEST_F(RecoveryTest, CorruptBlockFailsTheQueryAndBlocksCompaction) {
    {
        auto store = open(db());
        for (int i = 0; i < 2; ++i) {
            ASSERT_TRUE(store->append(points("m/a", i * 100, 100)).ok());
            ASSERT_TRUE(store->flush().ok());
        }
    }
    const auto victim = find_file(db(), "seg-");
    auto bytes = read_file(victim).value();
    bytes[20] ^= 0xFFU;
    write_bytes(victim, bytes);
    auto store = open(db());
    EXPECT_EQ(store->scan("m/a", 0, kAlways).error().code, ErrorCode::Corrupt);
    EXPECT_FALSE(store->compact().ok());
    EXPECT_EQ(store->stats().value().segments, 2U);
}

TEST_F(RecoveryTest, DamagedManifestIsReportedNotIgnored) {
    {
        auto store = open(db());
        ASSERT_TRUE(store->append(points("m/a", 0, 10)).ok());
        ASSERT_TRUE(store->flush().ok());
    }
    auto bytes = read_file(db() / "MANIFEST").value();
    bytes[18] ^= 0x01U;
    write_bytes(db() / "MANIFEST", bytes);
    EXPECT_EQ(Store::open(db()).error().code, ErrorCode::Corrupt);
}

TEST_F(RecoveryTest, MissingSegmentIsAnError) {
    {
        auto store = open(db());
        ASSERT_TRUE(store->append(points("m/a", 0, 10)).ok());
        ASSERT_TRUE(store->flush().ok());
    }
    fs::remove(find_file(db(), "seg-"));
    EXPECT_EQ(Store::open(db()).error().code, ErrorCode::Io);
}

}  // namespace
}  // namespace historian
