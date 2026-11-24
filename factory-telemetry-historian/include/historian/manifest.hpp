#pragma once

#include <cstdint>
#include <filesystem>
#include <vector>

#include "historian/types.hpp"

namespace historian {

/// The single source of truth for which files are live. Replaced atomically, so each flush or
/// compaction commits at one rename and leftovers from a crash are simply not listed.
struct Manifest {
    std::uint64_t next_id = 1;            ///< next segment / WAL number
    std::uint64_t wal_floor = 0;          ///< WALs below this number are fully flushed
    std::vector<std::uint64_t> segments;  ///< oldest first: later entries win on conflicts

    [[nodiscard]] Status save(const std::filesystem::path& directory) const;
    /// Returns a default manifest when the store is new.
    [[nodiscard]] static Result<Manifest> load(const std::filesystem::path& directory);
};

}  // namespace historian
