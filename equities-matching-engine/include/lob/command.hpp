#pragma once

#include <string>
#include <string_view>
#include <variant>

#include "lob/result.hpp"
#include "lob/types.hpp"

namespace lob {

struct SubmitCmd {
    std::string symbol;
    NewOrder order;
};
struct CancelCmd {
    std::string symbol;
    CancelOrder request;
};
struct AmendCmd {
    std::string symbol;
    AmendOrder request;
};
struct SessionCmd {
    enum class Kind : std::uint8_t { StartAuction, Uncross, Halt, Resume };
    std::string symbol;
    Kind kind;
};

using Command = std::variant<SubmitCmd, CancelCmd, AmendCmd, SessionCmd>;

[[nodiscard]] const std::string& symbol_of(const Command& c) noexcept;

/// Parses one line of the text order-entry protocol, for example
///   NEW sym=TGX id=17 owner=3 side=B type=LMT tif=DAY px=1234.50 qty=500
///   NEW sym=TGX id=18 owner=4 side=S type=ICE px=1235 qty=5000 peak=500 post=1 stp=CI
///   AMD sym=TGX id=17 px=1234.00 qty=300
///   CXL sym=TGX id=17
///   AUCTION sym=TGX   |   UNCROSS sym=TGX   |   HALT sym=TGX   |   RESUME sym=TGX
/// Prices are in pence with up to two decimal places. Unknown keys are errors, so a typo is
/// never silently ignored.
[[nodiscard]] Result<Command> parse_command(std::string_view line);

/// The canonical text form; parse_command(format_command(c)) == c.
[[nodiscard]] std::string format_command(const Command& c);

/// "1234.5" or "1234.50" -> 123450. Fails on more than two decimals or junk.
[[nodiscard]] Result<Price> parse_price(std::string_view text);

}  // namespace lob
