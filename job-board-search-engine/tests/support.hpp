#pragma once

#include <filesystem>
#include <random>
#include <string>

#include "jobsearch/types.hpp"

namespace jobsearch::testing {

inline JobAd job(std::string id, std::string title, std::string body,
                 std::string location = "Leeds", std::uint32_t salary_max = 40'000,
                 std::uint32_t posted_day = 10) {
    JobAd j;
    j.id = std::move(id);
    j.title = std::move(title);
    j.company = "Test Co";
    j.location = std::move(location);
    j.salary_min = salary_max / 2;
    j.salary_max = salary_max;
    j.posted_day = posted_day;
    j.body = std::move(body);
    return j;
}

/// A fresh, empty directory under the system temp dir, removed on destruction.
class TempDir {
  public:
    TempDir() {
        std::random_device rd;
        path_ = std::filesystem::temp_directory_path() /
                ("jobsearch-test-" + std::to_string(rd()) + std::to_string(rd()));
        std::filesystem::create_directories(path_);
    }
    ~TempDir() {
        std::error_code ec;
        std::filesystem::remove_all(path_, ec);
    }
    TempDir(const TempDir&) = delete;
    TempDir& operator=(const TempDir&) = delete;

    [[nodiscard]] const std::filesystem::path& path() const { return path_; }

  private:
    std::filesystem::path path_;
};

}  // namespace jobsearch::testing
