#include "historian/manifest.hpp"

#include <span>
#include <sstream>
#include <string>

#include "historian/bytes.hpp"
#include "historian/file.hpp"

namespace historian {

namespace {
constexpr const char* kName = "MANIFEST";
std::span<const std::uint8_t> as_bytes(const std::string& s) {
    return {reinterpret_cast<const std::uint8_t*>(s.data()), s.size()};
}
}  // namespace

Status Manifest::save(const std::filesystem::path& directory) const {
    std::ostringstream body;
    body << "historian 1\nnext " << next_id << "\nwal_floor " << wal_floor << "\nsegments "
         << segments.size();
    for (const auto id : segments) {
        body << ' ' << id;
    }
    body << '\n';
    std::string text = body.str();
    const auto crc = crc32(as_bytes(text));
    text += "crc " + std::to_string(crc) + "\n";
    return write_file_atomic(directory / kName, as_bytes(text));
}

Result<Manifest> Manifest::load(const std::filesystem::path& directory) {
    const auto path = directory / kName;
    if (!std::filesystem::exists(path)) {
        return Manifest{};
    }
    const auto bytes = read_file(path);
    if (!bytes) {
        return bytes.error();
    }
    const std::string text(bytes.value().begin(), bytes.value().end());
    const Error corrupt{ErrorCode::Corrupt, "MANIFEST is damaged"};
    const auto crc_at = text.rfind("crc ");
    if (crc_at == std::string::npos) {
        return corrupt;
    }
    std::istringstream in(text);
    std::string word;
    int version = 0;
    Manifest m;
    std::size_t count = 0;
    in >> word >> version >> word >> m.next_id >> word >> m.wal_floor >> word >> count;
    for (std::size_t i = 0; i < count && in; ++i) {
        std::uint64_t id = 0;
        in >> id;
        m.segments.push_back(id);
    }
    std::uint32_t crc = 0;
    in >> word >> crc;
    if (!in || version != 1 || crc != crc32(as_bytes(text.substr(0, crc_at)))) {
        return corrupt;
    }
    return m;
}

}  // namespace historian
