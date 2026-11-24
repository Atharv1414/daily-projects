#pragma once

#include <gtest/gtest.h>
#include <unistd.h>

#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include "historian/store.hpp"

namespace historian::testing_support {

inline constexpr TimestampMs kAlways = 4'000'000'000'000;

/// Fresh directory per test, removed afterwards.
class StoreTest : public ::testing::Test {
  protected:
    void SetUp() override {
        const auto* info = ::testing::UnitTest::GetInstance()->current_test_info();
        std::string name = std::string(info->test_suite_name()) + "_" + info->name();
        for (char& c : name) {
            c = c == '/' ? '_' : c;
        }
        directory_ = std::filesystem::temp_directory_path() /
                     ("historian_" + name + "_" + std::to_string(::getpid()));
        std::filesystem::remove_all(directory_);
        std::filesystem::create_directories(directory_);
    }
    void TearDown() override { std::filesystem::remove_all(directory_); }

    [[nodiscard]] std::filesystem::path db() const { return directory_ / "db"; }
    [[nodiscard]] const std::filesystem::path& directory() const { return directory_; }

    static std::unique_ptr<Store> open(const std::filesystem::path& path,
                                       std::size_t flush_samples = 1'000'000) {
        StoreOptions options;
        options.flush_samples = flush_samples;
        options.sync_wal = false;  // tests simulate crashes by copying files, not power loss
        auto store = Store::open(path, options);
        EXPECT_TRUE(store.ok()) << store.error().message;
        return store.ok() ? std::move(store).value() : nullptr;
    }

  private:
    std::filesystem::path directory_;
};

inline std::vector<Point> points(const std::string& series, TimestampMs from, int count,
                                 double value = 0.0) {
    std::vector<Point> out;
    for (int i = 0; i < count; ++i) {
        out.push_back({series, {from + i, value + i}});
    }
    return out;
}

}  // namespace historian::testing_support
