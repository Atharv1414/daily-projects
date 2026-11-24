#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include "historian/types.hpp"

namespace historian {

/// Owns a POSIX file descriptor.
class FileDescriptor {
  public:
    FileDescriptor() = default;
    explicit FileDescriptor(int fd) : fd_(fd) {}
    ~FileDescriptor() { reset(); }
    FileDescriptor(FileDescriptor&& other) noexcept : fd_(std::exchange(other.fd_, -1)) {}
    FileDescriptor& operator=(FileDescriptor&& other) noexcept;
    FileDescriptor(const FileDescriptor&) = delete;
    FileDescriptor& operator=(const FileDescriptor&) = delete;
    [[nodiscard]] int get() const noexcept { return fd_; }
    [[nodiscard]] bool valid() const noexcept { return fd_ >= 0; }
    void reset() noexcept;

  private:
    int fd_ = -1;
};

/// Read-only memory map. The pages stay valid after the file is unlinked, which lets a
/// compaction delete inputs while older queries still read them.
class MappedFile {
  public:
    [[nodiscard]] static Result<MappedFile> open(const std::filesystem::path& path);
    MappedFile() = default;
    ~MappedFile();
    MappedFile(MappedFile&& other) noexcept
        : data_(std::exchange(other.data_, nullptr)), size_(std::exchange(other.size_, 0)) {}
    MappedFile& operator=(MappedFile&& other) noexcept;
    MappedFile(const MappedFile&) = delete;
    MappedFile& operator=(const MappedFile&) = delete;
    [[nodiscard]] std::span<const std::uint8_t> bytes() const noexcept { return {data_, size_}; }

  private:
    const std::uint8_t* data_ = nullptr;
    std::size_t size_ = 0;
};

[[nodiscard]] Error io_error(const std::string& what, const std::filesystem::path& path);
[[nodiscard]] Status write_all(int fd, std::span<const std::uint8_t> bytes,
                               const std::filesystem::path& path);
[[nodiscard]] Status sync_file(int fd, const std::filesystem::path& path);
/// Makes a directory entry (create / rename / unlink) durable.
[[nodiscard]] Status sync_directory(const std::filesystem::path& directory);
/// temp file + fsync + rename + directory fsync: readers see the old or the new file.
[[nodiscard]] Status write_file_atomic(const std::filesystem::path& path,
                                       std::span<const std::uint8_t> bytes);
[[nodiscard]] Result<std::vector<std::uint8_t>> read_file(const std::filesystem::path& path);
/// Takes an exclusive advisory lock held until the descriptor closes.
[[nodiscard]] Result<FileDescriptor> lock_file(const std::filesystem::path& path);

}  // namespace historian
