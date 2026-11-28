#include "lob/journal.hpp"

#include <array>
#include <charconv>
#include <cstdio>
#include <sstream>
#include <stdexcept>

namespace lob {

namespace {

constexpr std::array<std::uint32_t, 256> make_crc_table() {
    std::array<std::uint32_t, 256> table{};
    for (std::uint32_t i = 0; i < 256; ++i) {
        std::uint32_t c = i;
        for (int k = 0; k < 8; ++k) c = (c & 1u) != 0 ? 0xEDB8'8320u ^ (c >> 1) : c >> 1;
        table[i] = c;
    }
    return table;
}

constexpr auto kCrcTable = make_crc_table();

}  // namespace

std::uint32_t crc32(std::string_view data) noexcept {
    std::uint32_t c = 0xFFFF'FFFFu;
    for (const char ch : data) {
        c = kCrcTable[(c ^ static_cast<std::uint8_t>(ch)) & 0xFFu] ^ (c >> 8);
    }
    return c ^ 0xFFFF'FFFFu;
}

std::string journal_record(std::uint64_t seq, const Command& command) {
    const std::string body = std::to_string(seq) + "|" + format_command(command);
    char crc[9];
    std::snprintf(crc, sizeof crc, "%08x", crc32(body));
    return body + "|" + crc + "\n";
}

JournalWriter::JournalWriter(const std::filesystem::path& path, std::uint64_t next_seq)
    : out_(path, std::ios::binary | std::ios::app), next_seq_(next_seq) {
    if (!out_) throw std::runtime_error("cannot open journal " + path.string());
}

void JournalWriter::append(const Command& command) {
    out_ << journal_record(next_seq_++, command);
    if (!out_) throw std::runtime_error("journal write failed");
}

void JournalWriter::flush() { out_.flush(); }

Result<JournalReadResult> read_journal_text(std::string_view text) {
    using R = Result<JournalReadResult>;
    JournalReadResult result;
    std::size_t pos = 0;
    std::uint64_t line_no = 0;
    while (pos < text.size()) {
        const auto nl = text.find('\n', pos);
        if (nl == std::string_view::npos) {
            // A record without its newline was cut off by a crash: it was never acknowledged,
            // so dropping it is safe.
            result.torn_tail_bytes = text.size() - pos;
            break;
        }
        const std::string_view line = text.substr(pos, nl - pos);
        pos = nl + 1;
        ++line_no;
        const auto where = " at record " + std::to_string(line_no);

        const auto first = line.find('|');
        const auto last = line.rfind('|');
        if (first == std::string_view::npos || first == last) {
            return R::failure("malformed record" + where);
        }
        const std::string_view body = line.substr(0, last);
        const std::string_view crc_text = line.substr(last + 1);
        std::uint32_t expected = 0;
        const auto [p, ec] =
            std::from_chars(crc_text.data(), crc_text.data() + crc_text.size(), expected, 16);
        if (ec != std::errc{} || p != crc_text.data() + crc_text.size() || crc_text.size() != 8) {
            return R::failure("bad checksum field" + where);
        }
        if (crc32(body) != expected) return R::failure("checksum mismatch" + where);

        std::uint64_t seq = 0;
        const std::string_view seq_text = line.substr(0, first);
        const auto [sp, sec] =
            std::from_chars(seq_text.data(), seq_text.data() + seq_text.size(), seq);
        if (sec != std::errc{} || sp != seq_text.data() + seq_text.size()) {
            return R::failure("bad sequence number" + where);
        }
        if (seq != result.last_seq + 1) {
            return R::failure("sequence gap: expected " + std::to_string(result.last_seq + 1) +
                              ", found " + std::to_string(seq) + where);
        }
        auto command = parse_command(line.substr(first + 1, last - first - 1));
        if (!command) return R::failure(command.error() + where);
        result.commands.push_back(std::move(command).value());
        result.last_seq = seq;
    }
    return result;
}

Result<JournalReadResult> read_journal(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return Result<JournalReadResult>::failure("cannot open " + path.string());
    std::ostringstream buffer;
    buffer << in.rdbuf();
    return read_journal_text(buffer.str());
}

}  // namespace lob
