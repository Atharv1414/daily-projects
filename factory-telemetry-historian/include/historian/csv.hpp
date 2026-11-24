#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <variant>

#include "historian/types.hpp"

namespace historian {

/// Why a source line was refused. Counted and written to the quarantine file.
enum class RejectReason {
    FieldCount,
    BadTimestamp,
    BadMachine,
    UnknownSensor,
    BadValue,
    OutOfRange,
};
inline constexpr std::size_t kRejectReasons = 6;

[[nodiscard]] const char* to_string(RejectReason reason) noexcept;

/// Physical limits of a sensor type. Readings outside them are faults, not measurements.
struct SensorSpec {
    std::string_view name;
    double low;
    double high;
};

[[nodiscard]] std::optional<SensorSpec> find_sensor(std::string_view name) noexcept;

/// Accepts epoch milliseconds or ISO-8601 UTC (`2026-11-02T06:00:00[.fff]Z`).
[[nodiscard]] std::optional<TimestampMs> parse_timestamp(std::string_view text) noexcept;
[[nodiscard]] std::string format_timestamp(TimestampMs ts);

/// Parses `timestamp,machine,sensor,value` into a point on series `machine/sensor`.
[[nodiscard]] std::variant<Point, RejectReason> parse_line(std::string_view line);

}  // namespace historian
