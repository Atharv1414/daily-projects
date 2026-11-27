using Rollout.Domain;

namespace Rollout.Application;

/// <summary>Base for failures the API turns into problem details. Anything else is a bug and stays a 500.</summary>
public abstract class RolloutException(string message) : Exception(message);

public sealed class UnknownEnvironmentException(string environment)
    : RolloutException($"There is no environment called '{environment}'.");

public sealed class FlagNotFoundException(string environment, string key)
    : RolloutException($"No flag '{key}' in {environment}.");

public sealed class FlagValidationException(IReadOnlyList<ValidationError> errors)
    : RolloutException($"The flag definition has {errors.Count} problem(s).")
{
    public IReadOnlyList<ValidationError> Errors { get; } = errors;
}

/// <summary>Someone else changed the flag since the caller read it.</summary>
public sealed class VersionConflictException(string key, long? expected, long current)
    : RolloutException($"'{key}' is at version {current}, not {expected?.ToString(System.Globalization.CultureInfo.InvariantCulture) ?? "new"}. Reload it and apply your change again.")
{
    public long Current { get; } = current;
}

/// <summary>Changing an existing flag needs the version the caller last saw.</summary>
public sealed class VersionRequiredException(string key)
    : RolloutException($"'{key}' already exists: send If-Match with the version you are changing.");

public sealed class FlagInUseException(string key, IReadOnlyList<string> dependants)
    : RolloutException($"'{key}' is a prerequisite of {string.Join(", ", dependants)}; remove those links first.");

public sealed class NotAnExperimentException(string key)
    : RolloutException($"'{key}' does not split traffic by weight, so there is no sample ratio to check.");
