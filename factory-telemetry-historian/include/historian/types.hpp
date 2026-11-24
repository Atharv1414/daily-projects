#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <variant>

namespace historian {

/// Milliseconds since the Unix epoch, UTC.
using TimestampMs = std::int64_t;

struct Sample {
    TimestampMs ts = 0;
    double value = 0.0;
    friend bool operator==(const Sample&, const Sample&) = default;
};

/// One measurement addressed to a series such as `press-01/temp_c`.
struct Point {
    std::string series;
    Sample sample;
};

enum class ErrorCode { Io, Corrupt, InvalidArgument, Locked };

[[nodiscard]] const char* to_string(ErrorCode code) noexcept;

struct Error {
    ErrorCode code = ErrorCode::Io;
    std::string message;
};

/// Minimal stand-in for C++23 std::expected: either a value or an Error.
template <typename T>
class [[nodiscard]] Result {
  public:
    Result(T value) : state_(std::move(value)) {}
    Result(Error error) : state_(std::move(error)) {}

    [[nodiscard]] bool ok() const noexcept { return std::holds_alternative<T>(state_); }
    explicit operator bool() const noexcept { return ok(); }
    [[nodiscard]] T& value() & { return std::get<T>(state_); }
    [[nodiscard]] const T& value() const& { return std::get<T>(state_); }
    // By value, so `for (auto& x : f().value())` cannot dangle.
    [[nodiscard]] T value() && { return std::get<T>(std::move(state_)); }
    [[nodiscard]] const Error& error() const { return std::get<Error>(state_); }

  private:
    std::variant<T, Error> state_;
};

/// Success, or the reason for failure.
class [[nodiscard]] Status {
  public:
    Status() = default;
    Status(Error error) : error_(std::move(error)) {}
    [[nodiscard]] bool ok() const noexcept { return !error_.has_value(); }
    [[nodiscard]] const Error& error() const { return error_.value(); }

  private:
    std::optional<Error> error_;
};

}  // namespace historian
