#pragma once

#include <array>
#include <cstdint>
#include <iosfwd>

#include "historian/csv.hpp"
#include "historian/store.hpp"

namespace historian {

struct IngestOptions {
    unsigned parsers = 4;
    std::size_t batch_lines = 4096;
    std::size_t max_in_flight = 16;  ///< batches read but not yet stored (back-pressure)
};

struct IngestReport {
    std::uint64_t lines = 0;
    std::uint64_t accepted = 0;
    std::uint64_t rejected = 0;
    std::array<std::uint64_t, kRejectReasons> by_reason{};
};

/// reader thread -> parser threads -> this thread, which stores batches in file order.
/// Rejected lines go to `quarantine` as `line_number,reason,original text`.
[[nodiscard]] Result<IngestReport> ingest_csv(std::istream& in, Store& store,
                                              std::ostream& quarantine,
                                              const IngestOptions& options = {});

}  // namespace historian
