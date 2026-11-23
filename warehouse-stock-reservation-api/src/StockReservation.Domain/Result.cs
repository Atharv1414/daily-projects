namespace StockReservation.Domain;

/// <summary>How an error should be surfaced to callers (maps 1:1 onto HTTP status families).</summary>
public enum ErrorKind
{
    Validation,
    NotFound,
    Conflict,
    InsufficientStock,
    InvalidState,
}

/// <summary>A domain error with a stable machine-readable code.</summary>
public sealed record DomainError(string Code, string Message, ErrorKind Kind)
{
    public static DomainError Validation(string code, string message) => new(code, message, ErrorKind.Validation);

    public static DomainError NotFound(string code, string message) => new(code, message, ErrorKind.NotFound);

    public static DomainError Conflict(string code, string message) => new(code, message, ErrorKind.Conflict);

    public static DomainError InvalidState(string code, string message) => new(code, message, ErrorKind.InvalidState);

    public static DomainError Insufficient(string code, string message) =>
        new(code, message, ErrorKind.InsufficientStock);
}

/// <summary>Result of an operation that has no value on success.</summary>
public readonly record struct Result
{
    private Result(DomainError? error) => Error = error;

    public DomainError? Error { get; }

    public bool IsSuccess => Error is null;

    public static Result Success() => new(null);

    public static Result Failure(DomainError error) => new(error);

    public static implicit operator Result(DomainError error) => Failure(error);
}

/// <summary>Result of an operation that returns a value on success.</summary>
[System.Diagnostics.CodeAnalysis.SuppressMessage(
    "Design",
    "CA1000:Do not declare static members on generic types",
    Justification = "Factory methods are the idiomatic way to build a Result.")]
public readonly record struct Result<T>
{
    private Result(T? value, DomainError? error)
    {
        Value = value;
        Error = error;
    }

    public T? Value { get; }

    public DomainError? Error { get; }

    public bool IsSuccess => Error is null;

    public static Result<T> Success(T value) => new(value, null);

    public static Result<T> Failure(DomainError error) => new(default, error);

    public static implicit operator Result<T>(T value) => Success(value);

    public static implicit operator Result<T>(DomainError error) => Failure(error);
}
