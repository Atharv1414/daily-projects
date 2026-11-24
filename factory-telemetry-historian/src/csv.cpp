#include "historian/csv.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace historian {

namespace {

constexpr std::array<SensorSpec, 6> kSensors{{
    {"temp_c", -40.0, 400.0},
    {"vibration_mm_s", 0.0, 100.0},
    {"spindle_rpm", 0.0, 30000.0},
    {"power_kw", 0.0, 500.0},
    {"pressure_bar", 0.0, 400.0},
    {"part_count", 0.0, 1e9},
}};

constexpr TimestampMs kEarliest = 1'577'836'800'000;  // 2020-01-01
constexpr TimestampMs kLatest = 2'051'222'400'000;    // 2035-01-01

std::string_view trim(std::string_view s) {
    while (!s.empty() && (s.front() == ' ' || s.front() == '\t')) {
        s.remove_prefix(1);
    }
    while (!s.empty() && (s.back() == ' ' || s.back() == '\t' || s.back() == '\r')) {
        s.remove_suffix(1);
    }
    return s;
}

template <typename T>
bool parse_integer(std::string_view s, T& out) {
    const auto [end, error] = std::from_chars(s.data(), s.data() + s.size(), out);
    return error == std::errc{} && end == s.data() + s.size() && !s.empty();
}

// Unsigned target, so "-1" or "+1" inside a date is refused.
bool parse_digits(std::string_view s, unsigned& out) { return parse_integer(s, out); }

std::optional<TimestampMs> parse_iso(std::string_view s) {
    if (s.size() < 20 || s.back() != 'Z' || s[4] != '-' || s[7] != '-' || s[10] != 'T' ||
        s[13] != ':' || s[16] != ':') {
        return std::nullopt;
    }
    unsigned year = 0;
    unsigned month = 0;
    unsigned day = 0;
    unsigned hour = 0;
    unsigned minute = 0;
    unsigned second = 0;
    unsigned millis = 0;
    if (!parse_digits(s.substr(0, 4), year) || !parse_digits(s.substr(5, 2), month) ||
        !parse_digits(s.substr(8, 2), day) || !parse_digits(s.substr(11, 2), hour) ||
        !parse_digits(s.substr(14, 2), minute) || !parse_digits(s.substr(17, 2), second)) {
        return std::nullopt;
    }
    if (s.size() > 20 &&
        (s.size() != 24 || s[19] != '.' || !parse_digits(s.substr(20, 3), millis))) {
        return std::nullopt;
    }
    const std::chrono::year_month_day date{std::chrono::year(static_cast<int>(year)),
                                           std::chrono::month(month), std::chrono::day(day)};
    if (!date.ok() || hour > 23 || minute > 59 || second > 59) {
        return std::nullopt;
    }
    const auto days = std::chrono::sys_days(date).time_since_epoch();
    const auto base = std::chrono::duration_cast<std::chrono::milliseconds>(days).count();
    return static_cast<TimestampMs>(base) + ((hour * 60LL + minute) * 60LL + second) * 1000LL +
           millis;
}

std::optional<double> parse_double(std::string_view s) {
    // libc++ has no floating-point from_chars on every supported platform, so use strtod on
    // a bounded, terminated copy. The character filter refuses hex, "inf" and "nan".
    std::array<char, 40> buffer{};
    const bool plain = std::ranges::all_of(s, [](char c) {
        return (c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+' || c == 'e' || c == 'E';
    });
    if (s.empty() || s.size() >= buffer.size() || !plain) {
        return std::nullopt;
    }
    std::ranges::copy(s, buffer.begin());
    char* end = nullptr;
    const double value = std::strtod(buffer.data(), &end);
    if (end != buffer.data() + s.size() || !std::isfinite(value)) {
        return std::nullopt;
    }
    return value;
}

bool valid_machine(std::string_view s) {
    return !s.empty() && s.size() <= 64 && std::ranges::all_of(s, [](char c) {
        return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '_';
    });
}

}  // namespace

const char* to_string(RejectReason reason) noexcept {
    switch (reason) {
        case RejectReason::FieldCount:
            return "field_count";
        case RejectReason::BadTimestamp:
            return "bad_timestamp";
        case RejectReason::BadMachine:
            return "bad_machine";
        case RejectReason::UnknownSensor:
            return "unknown_sensor";
        case RejectReason::BadValue:
            return "bad_value";
        case RejectReason::OutOfRange:
            return "out_of_range";
    }
    return "unknown";
}

std::optional<SensorSpec> find_sensor(std::string_view name) noexcept {
    const auto it = std::ranges::find(kSensors, name, &SensorSpec::name);
    return it == kSensors.end() ? std::nullopt : std::optional{*it};
}

std::optional<TimestampMs> parse_timestamp(std::string_view text) noexcept {
    TimestampMs ts = 0;
    if (!parse_integer(text, ts)) {
        const auto iso = parse_iso(text);
        if (!iso) {
            return std::nullopt;
        }
        ts = *iso;
    }
    // A PLC with a dead clock battery reports 1970 or 2099; storing that breaks retention.
    if (ts < kEarliest || ts >= kLatest) {
        return std::nullopt;
    }
    return ts;
}

std::string format_timestamp(TimestampMs ts) {
    using std::chrono::milliseconds;
    const std::chrono::sys_time<milliseconds> time{milliseconds(ts)};
    const auto day = std::chrono::floor<std::chrono::days>(time);
    const std::chrono::year_month_day date(day);
    const std::chrono::hh_mm_ss clock(time - day);
    std::array<char, 64> buffer{};
    std::snprintf(buffer.data(), buffer.size(), "%04d-%02u-%02uT%02d:%02d:%02d.%03dZ",
                  static_cast<int>(date.year()), static_cast<unsigned>(date.month()),
                  static_cast<unsigned>(date.day()), static_cast<int>(clock.hours().count()),
                  static_cast<int>(clock.minutes().count()),
                  static_cast<int>(clock.seconds().count()),
                  static_cast<int>(clock.subseconds().count()));
    return buffer.data();
}

std::variant<Point, RejectReason> parse_line(std::string_view line) {
    std::array<std::string_view, 4> fields;
    std::size_t count = 0;
    while (count < fields.size()) {
        const auto comma = line.find(',');
        fields[count++] = trim(line.substr(0, comma));
        if (comma == std::string_view::npos) {
            line = {};
            break;
        }
        line.remove_prefix(comma + 1);
        if (count == fields.size()) {
            return RejectReason::FieldCount;  // a comma followed the fourth field
        }
    }
    if (count != fields.size()) {
        return RejectReason::FieldCount;
    }
    const auto ts = parse_timestamp(fields[0]);
    if (!ts) {
        return RejectReason::BadTimestamp;
    }
    if (!valid_machine(fields[1])) {
        return RejectReason::BadMachine;
    }
    const auto sensor = find_sensor(fields[2]);
    if (!sensor) {
        return RejectReason::UnknownSensor;
    }
    const auto value = parse_double(fields[3]);
    if (!value) {
        return RejectReason::BadValue;
    }
    if (*value < sensor->low || *value > sensor->high) {
        return RejectReason::OutOfRange;
    }
    std::string series(fields[1]);
    series += '/';
    series += fields[2];
    return Point{std::move(series), {*ts, *value}};
}

}  // namespace historian
