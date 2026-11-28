#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>
#include <vector>

#include "lob/command.hpp"
#include "lob/result.hpp"

namespace lob {

[[nodiscard]] std::uint32_t crc32(std::string_view data) noexcept;

/// Append-only command journal. Every accepted command is written BEFORE it is applied, as
/// `<seq>|<command text>|<crc32 hex>\n`. Replaying the journal through a fresh engine gives the
/// same events and the same book state, because matching is deterministic.
class JournalWriter {
  public:
    /// Opens for append; existing records are kept and numbering continues after them.
    explicit JournalWriter(const std::filesystem::path& path, std::uint64_t next_seq = 1);
    void append(const Command& command);
    void flush();
    [[nodiscard]] std::uint64_t next_seq() const noexcept { return next_seq_; }

  private:
    std::ofstream out_;
    std::uint64_t next_seq_;
};

struct JournalReadResult {
    std::vector<Command> commands;
    std::uint64_t last_seq = 0;
    /// Number of trailing bytes ignored because the last record was torn (crash mid-write).
    std::size_t torn_tail_bytes = 0;
};

/// Reads the whole journal. A torn final record (no newline) is dropped and reported; a
/// corrupt record in the middle (bad CRC, gap in sequence, unparseable command) is an error,
/// because silently skipping it would replay a different market.
[[nodiscard]] Result<JournalReadResult> read_journal(const std::filesystem::path& path);
/// Same, from an in-memory buffer (used by tests).
[[nodiscard]] Result<JournalReadResult> read_journal_text(std::string_view text);

[[nodiscard]] std::string journal_record(std::uint64_t seq, const Command& command);

}  // namespace lob
