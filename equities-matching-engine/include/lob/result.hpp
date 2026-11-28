#pragma once

#include <string>
#include <utility>
#include <variant>

namespace lob {

/// A small stand-in for std::expected (not yet in every standard library we build with).
template <class T>
class [[nodiscard]] Result {
  public:
    Result(T value) : data_(std::move(value)) {}  // NOLINT(google-explicit-constructor)
    static Result failure(std::string message) { return Result(Error{std::move(message)}); }

    [[nodiscard]] bool ok() const noexcept { return std::holds_alternative<T>(data_); }
    explicit operator bool() const noexcept { return ok(); }
    [[nodiscard]] const T& value() const& { return std::get<T>(data_); }
    [[nodiscard]] T&& value() && { return std::get<T>(std::move(data_)); }
    [[nodiscard]] const std::string& error() const { return std::get<Error>(data_).message; }

  private:
    struct Error {
        std::string message;
    };
    explicit Result(Error e) : data_(std::move(e)) {}
    std::variant<T, Error> data_;
};

}  // namespace lob
