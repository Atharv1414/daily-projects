#pragma once

#include <cstdint>
#include <filesystem>
#include <span>
#include <vector>

#include "historian/bytes.hpp"
#include "historian/file.hpp"
#include "historian/types.hpp"

namespace historian {

/// Append-only log. One record is one batch: [u32 length][u32 crc][payload], so a batch is
/// recovered entirely or not at all.
class WalWriter {
  public:
    [[nodiscard]] static Result<WalWriter> create(std::filesystem::path path, bool sync);
    [[nodiscard]] Status append(std::span<const Point> batch);
    [[nodiscard]] std::uint64_t bytes_written() const noexcept { return offset_; }

  private:
    WalWriter(std::filesystem::path path, FileDescriptor fd, bool sync)
        : path_(std::move(path)), fd_(std::move(fd)), sync_(sync) {}
    std::filesystem::path path_;
    FileDescriptor fd_;
    bool sync_;
    bool broken_ = false;
    std::uint64_t offset_ = 0;
};

struct WalReplay {
    std::vector<std::vector<Point>> batches;
    std::uint64_t valid_bytes = 0;
    bool torn_tail = false;  ///< file ended in a partial or corrupt record
};

/// Reads every intact record, stopping at the first damaged one.
[[nodiscard]] Result<WalReplay> replay_wal(const std::filesystem::path& path);

}  // namespace historian
