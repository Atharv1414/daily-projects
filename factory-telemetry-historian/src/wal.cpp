#include "historian/wal.hpp"

#include <fcntl.h>
#include <unistd.h>

#include <string>
#include <string_view>
#include <unordered_map>

namespace historian {

namespace {

// A batch repeats few series names, so names are stored once and referenced by index.
std::vector<std::uint8_t> encode_payload(std::span<const Point> batch) {
    std::unordered_map<std::string_view, std::uint32_t> ids;
    std::vector<std::string_view> names;
    for (const Point& p : batch) {
        if (ids.try_emplace(p.series, static_cast<std::uint32_t>(names.size())).second) {
            names.push_back(p.series);
        }
    }
    ByteWriter out;
    out.u32(static_cast<std::uint32_t>(names.size()));
    for (const auto name : names) {
        out.string(name);
    }
    out.u32(static_cast<std::uint32_t>(batch.size()));
    for (const Point& p : batch) {
        out.u32(ids.at(p.series));
        out.i64(p.sample.ts);
        out.f64(p.sample.value);
    }
    return out.bytes();
}

bool decode_payload(std::span<const std::uint8_t> payload, std::vector<Point>& batch) {
    ByteReader in(payload);
    const std::uint32_t name_count = in.u32();
    std::vector<std::string> names;
    for (std::uint32_t i = 0; i < name_count && in.ok(); ++i) {
        names.push_back(in.string());
    }
    const std::uint32_t count = in.u32();
    for (std::uint32_t i = 0; i < count && in.ok(); ++i) {
        const std::uint32_t id = in.u32();
        const std::int64_t ts = in.i64();
        const double value = in.f64();
        if (!in.ok() || id >= names.size()) {
            return false;
        }
        batch.push_back({names[id], {ts, value}});
    }
    return in.ok() && in.remaining() == 0;
}

}  // namespace

Result<WalWriter> WalWriter::create(std::filesystem::path path, bool sync) {
    FileDescriptor fd(::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0644));
    if (!fd.valid()) {
        return io_error("create", path);
    }
    if (auto s = sync_directory(path.parent_path()); !s.ok()) {
        return s.error();
    }
    return WalWriter(std::move(path), std::move(fd), sync);
}

Status WalWriter::append(std::span<const Point> batch) {
    if (broken_) {
        return Error{ErrorCode::Io, "WAL is unusable after an earlier write failure; reopen"};
    }
    const auto payload = encode_payload(batch);
    ByteWriter record;
    record.u32(static_cast<std::uint32_t>(payload.size()));
    record.u32(crc32(payload));
    record.raw(payload);
    auto status = write_all(fd_.get(), record.bytes(), path_);
    if (status.ok() && sync_) {
        status = sync_file(fd_.get(), path_);
    }
    if (!status.ok()) {
        // After a failed write or fsync the tail is unknown. Appending past it would put
        // acknowledged records behind a torn one, where replay never reaches them.
        broken_ = true;
        return status;
    }
    offset_ += record.size();
    return {};
}

Result<WalReplay> replay_wal(const std::filesystem::path& path) {
    const auto file = read_file(path);
    if (!file) {
        return file.error();
    }
    WalReplay replay;
    ByteReader in(file.value());
    while (in.remaining() > 0) {
        const std::uint32_t length = in.u32();
        const std::uint32_t crc = in.u32();
        const auto payload = in.raw(length);
        std::vector<Point> batch;
        if (!in.ok() || crc32(payload) != crc || !decode_payload(payload, batch)) {
            replay.torn_tail = true;
            break;
        }
        replay.batches.push_back(std::move(batch));
        replay.valid_bytes += 8ULL + length;
    }
    return replay;
}

}  // namespace historian
