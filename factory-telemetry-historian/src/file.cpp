#include "historian/file.hpp"

#include <fcntl.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <cstring>

namespace historian {

const char* to_string(ErrorCode code) noexcept {
    switch (code) {
        case ErrorCode::Io:
            return "io";
        case ErrorCode::Corrupt:
            return "corrupt";
        case ErrorCode::InvalidArgument:
            return "invalid-argument";
        case ErrorCode::Locked:
            return "locked";
    }
    return "unknown";
}

FileDescriptor& FileDescriptor::operator=(FileDescriptor&& other) noexcept {
    if (this != &other) {
        reset();
        fd_ = std::exchange(other.fd_, -1);
    }
    return *this;
}

void FileDescriptor::reset() noexcept {
    if (fd_ >= 0) {
        ::close(fd_);
        fd_ = -1;
    }
}

MappedFile::~MappedFile() {
    if (data_ != nullptr) {
        ::munmap(const_cast<std::uint8_t*>(data_), size_);
    }
}

MappedFile& MappedFile::operator=(MappedFile&& other) noexcept {
    std::swap(data_, other.data_);
    std::swap(size_, other.size_);
    return *this;
}

Result<MappedFile> MappedFile::open(const std::filesystem::path& path) {
    const FileDescriptor fd(::open(path.c_str(), O_RDONLY | O_CLOEXEC));
    if (!fd.valid()) {
        return io_error("open", path);
    }
    struct stat info{};
    if (::fstat(fd.get(), &info) != 0) {
        return io_error("stat", path);
    }
    MappedFile file;
    if (info.st_size > 0) {
        const auto size = static_cast<std::size_t>(info.st_size);
        void* data = ::mmap(nullptr, size, PROT_READ, MAP_PRIVATE, fd.get(), 0);
        // MAP_FAILED is a macro containing a C-style cast, hence the explicit comparison.
        if (data == reinterpret_cast<void*>(-1)) {
            return io_error("mmap", path);
        }
        file.data_ = static_cast<const std::uint8_t*>(data);
        file.size_ = size;
    }
    return file;
}

Error io_error(const std::string& what, const std::filesystem::path& path) {
    return {ErrorCode::Io, what + " " + path.string() + ": " + std::strerror(errno)};
}

Status write_all(int fd, std::span<const std::uint8_t> bytes, const std::filesystem::path& path) {
    while (!bytes.empty()) {
        const ssize_t n = ::write(fd, bytes.data(), bytes.size());
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return io_error("write", path);
        }
        bytes = bytes.subspan(static_cast<std::size_t>(n));
    }
    return {};
}

Status sync_file(int fd, const std::filesystem::path& path) {
    if (::fsync(fd) != 0) {
        return io_error("fsync", path);
    }
    return {};
}

Status sync_directory(const std::filesystem::path& directory) {
    const FileDescriptor fd(::open(directory.c_str(), O_RDONLY | O_CLOEXEC));
    if (!fd.valid()) {
        return io_error("open directory", directory);
    }
    return sync_file(fd.get(), directory);
}

Status write_file_atomic(const std::filesystem::path& path, std::span<const std::uint8_t> bytes) {
    auto temporary = path;
    temporary += ".tmp";
    {
        const FileDescriptor fd(
            ::open(temporary.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644));
        if (!fd.valid()) {
            return io_error("create", temporary);
        }
        if (auto s = write_all(fd.get(), bytes, temporary); !s.ok()) {
            return s;
        }
        if (auto s = sync_file(fd.get(), temporary); !s.ok()) {
            return s;
        }
    }
    if (::rename(temporary.c_str(), path.c_str()) != 0) {
        return io_error("rename", path);
    }
    return sync_directory(path.parent_path());
}

Result<std::vector<std::uint8_t>> read_file(const std::filesystem::path& path) {
    const FileDescriptor fd(::open(path.c_str(), O_RDONLY | O_CLOEXEC));
    if (!fd.valid()) {
        return io_error("open", path);
    }
    std::vector<std::uint8_t> out;
    std::array<std::uint8_t, 65536> buffer{};
    for (;;) {
        const ssize_t n = ::read(fd.get(), buffer.data(), buffer.size());
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return io_error("read", path);
        }
        if (n == 0) {
            return out;
        }
        out.insert(out.end(), buffer.begin(), buffer.begin() + n);
    }
}

Result<FileDescriptor> lock_file(const std::filesystem::path& path) {
    FileDescriptor fd(::open(path.c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0644));
    if (!fd.valid()) {
        return io_error("open", path);
    }
    if (::flock(fd.get(), LOCK_EX | LOCK_NB) != 0) {
        return Error{ErrorCode::Locked, "store is already open in another process"};
    }
    return fd;
}

}  // namespace historian
