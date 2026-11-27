using System.Text.Json;
using System.Text.RegularExpressions;
using Rollout.Domain.Expressions;

namespace Rollout.Domain;

/// <summary>A problem with a flag definition, addressed by a JSON-path-like location.</summary>
public sealed record ValidationError(string Path, string Message);

/// <summary>Checks a definition on its own, then against the other flags in its environment.</summary>
public static partial class FlagValidator
{
    public const int MaxVariants = 20;
    public const int MaxRules = 50;
    public const int MaxTargetsPerVariant = 1_000;
    public const int MaxValueBytes = 4_096;

    [GeneratedRegex("^[a-z0-9][a-z0-9._-]{1,63}$")]
    private static partial Regex KeyPattern();

    public static IReadOnlyList<ValidationError> Validate(FlagDefinition flag)
    {
        ArgumentNullException.ThrowIfNull(flag);
        var errors = new List<ValidationError>();
        void Add(string path, string message) => errors.Add(new ValidationError(path, message));

        if (!KeyPattern().IsMatch(flag.Key ?? string.Empty))
        {
            Add("key", "Use 2 to 64 lowercase letters, digits, '.', '-' or '_', starting with a letter or digit.");
        }

        var variants = flag.Variants ?? [];
        var keys = variants.Select(v => v.Key).ToList();
        if (variants.Count is 0 or > MaxVariants)
        {
            Add("variants", $"A flag needs between 1 and {MaxVariants} variants.");
        }

        foreach (var duplicate in keys.GroupBy(k => k, StringComparer.Ordinal).Where(g => g.Count() > 1))
        {
            Add("variants", $"Variant '{duplicate.Key}' is defined more than once.");
        }

        for (var i = 0; i < variants.Count; i++)
        {
            if (variants[i].Value.ValueKind == JsonValueKind.Undefined)
            {
                Add($"variants[{i}].value", "Every variant needs a value.");
            }
            else if (variants[i].Value.GetRawText().Length > MaxValueBytes)
            {
                Add($"variants[{i}].value", $"Values are limited to {MaxValueBytes} bytes; store large config elsewhere.");
            }
        }

        if (flag.Kind == FlagKind.Boolean)
        {
            var isBoolean = variants.Count == 2
                && variants.Any(v => v.Key == "on" && v.Value.ValueKind == JsonValueKind.True)
                && variants.Any(v => v.Key == "off" && v.Value.ValueKind == JsonValueKind.False);
            if (!isBoolean)
            {
                Add("variants", "A boolean flag has exactly the variants on (true) and off (false).");
            }
        }

        var known = keys.ToHashSet(StringComparer.Ordinal);
        if (!known.Contains(flag.OffVariant ?? string.Empty))
        {
            Add("offVariant", $"Unknown variant '{flag.OffVariant}'.");
        }

        ValidateServe("fallthrough", flag.Fallthrough, known, Add);

        var rules = flag.RuleList;
        if (rules.Count > MaxRules)
        {
            Add("rules", $"At most {MaxRules} rules.");
        }

        foreach (var duplicate in rules.GroupBy(r => r.Id, StringComparer.Ordinal).Where(g => g.Count() > 1))
        {
            Add("rules", $"Rule id '{duplicate.Key}' is used more than once.");
        }

        for (var i = 0; i < rules.Count; i++)
        {
            try
            {
                Parser.Parse(rules[i].Condition ?? string.Empty);
            }
            catch (RuleSyntaxException e)
            {
                Add($"rules[{i}].condition", e.Message);
            }

            ValidateServe($"rules[{i}].serve", rules[i].Serve, known, Add);
        }

        var targets = flag.TargetLists;
        var seenUnits = new HashSet<string>(StringComparer.Ordinal);
        for (var i = 0; i < targets.Count; i++)
        {
            if (!known.Contains(targets[i].Variant))
            {
                Add($"targets[{i}].variant", $"Unknown variant '{targets[i].Variant}'.");
            }

            if (targets[i].UnitKeys.Count > MaxTargetsPerVariant)
            {
                Add($"targets[{i}].unitKeys", $"At most {MaxTargetsPerVariant} keys per variant; use a rule for larger groups.");
            }

            foreach (var unit in targets[i].UnitKeys.Where(u => !seenUnits.Add(u)))
            {
                Add($"targets[{i}].unitKeys", $"'{unit}' is targeted more than once.");
            }
        }

        for (var i = 0; i < flag.PrerequisiteList.Count; i++)
        {
            if (flag.PrerequisiteList[i].FlagKey == flag.Key)
            {
                Add($"prerequisites[{i}]", "A flag cannot be its own prerequisite.");
            }
        }

        if (string.IsNullOrWhiteSpace(flag.BucketBy))
        {
            Add("bucketBy", "Name the context attribute to bucket by, such as userId or householdId.");
        }

        return errors;
    }

    /// <summary>
    /// Checks the prerequisites of <paramref name="candidate"/> against the environment it is joining:
    /// they must exist, name real variants, and not form a cycle.
    /// </summary>
    public static IReadOnlyList<ValidationError> ValidateInSet(FlagDefinition candidate, IReadOnlyDictionary<string, FlagDefinition> others)
    {
        ArgumentNullException.ThrowIfNull(candidate);
        ArgumentNullException.ThrowIfNull(others);
        var errors = new List<ValidationError>();
        var all = new Dictionary<string, FlagDefinition>(others, StringComparer.Ordinal) { [candidate.Key] = candidate };
        for (var i = 0; i < candidate.PrerequisiteList.Count; i++)
        {
            var prerequisite = candidate.PrerequisiteList[i];
            if (prerequisite.FlagKey == candidate.Key)
            {
                continue;
            }

            if (!all.TryGetValue(prerequisite.FlagKey, out var parent))
            {
                errors.Add(new ValidationError($"prerequisites[{i}]", $"No flag '{prerequisite.FlagKey}' in this environment."));
            }
            else if (parent.Variants.All(v => v.Key != prerequisite.Variant))
            {
                errors.Add(new ValidationError($"prerequisites[{i}]", $"'{prerequisite.FlagKey}' has no variant '{prerequisite.Variant}'."));
            }
        }

        if (FindCycle(candidate.Key, all) is { } cycle)
        {
            errors.Add(new ValidationError("prerequisites", $"Prerequisites form a cycle: {string.Join(" -> ", cycle)}."));
        }

        return errors;
    }

    /// <summary>Depth-first search from <paramref name="start"/>; returns the cycle's path if one is reachable.</summary>
    public static IReadOnlyList<string>? FindCycle(string start, IReadOnlyDictionary<string, FlagDefinition> flags)
    {
        ArgumentNullException.ThrowIfNull(flags);
        var path = new List<string>();
        var onPath = new HashSet<string>(StringComparer.Ordinal);
        var done = new HashSet<string>(StringComparer.Ordinal);

        List<string>? Visit(string key)
        {
            if (onPath.Contains(key))
            {
                return [.. path.SkipWhile(k => k != key), key];
            }

            if (!done.Add(key) || !flags.TryGetValue(key, out var flag))
            {
                return null;
            }

            path.Add(key);
            onPath.Add(key);
            foreach (var prerequisite in flag.PrerequisiteList)
            {
                if (Visit(prerequisite.FlagKey) is { } found)
                {
                    return found;
                }
            }

            onPath.Remove(key);
            path.RemoveAt(path.Count - 1);
            return null;
        }

        return Visit(start);
    }

    private static void ValidateServe(string path, Serve? serve, HashSet<string> known, Action<string, string> add)
    {
        if (serve is null)
        {
            add(path, "Say what to serve.");
            return;
        }

        var set = (serve.Variant is not null ? 1 : 0) + (serve.Rollout is not null ? 1 : 0) + (serve.Progressive is not null ? 1 : 0);
        if (set != 1)
        {
            add(path, "Set exactly one of variant, rollout or progressive.");
            return;
        }

        foreach (var variant in serve.ReferencedVariants().Where(v => !known.Contains(v)))
        {
            add(path, $"Unknown variant '{variant}'.");
        }

        if (serve.Rollout is { } rollout)
        {
            if (rollout.Any(w => w.Weight < 0))
            {
                add($"{path}.rollout", "Weights cannot be negative.");
            }

            var total = rollout.Sum(w => (long)w.Weight);
            if (total != Bucketing.Buckets)
            {
                add($"{path}.rollout", $"Weights must add up to {Bucketing.Buckets:N0} (100%); they add up to {total:N0}.");
            }

            if (rollout.Select(w => w.Variant).Distinct(StringComparer.Ordinal).Count() != rollout.Count)
            {
                add($"{path}.rollout", "Each variant may appear once in a rollout.");
            }
        }

        if (serve.Progressive is { } progressive)
        {
            if (progressive.From == progressive.To)
            {
                add($"{path}.progressive", "From and to must be different variants.");
            }

            if (progressive.Steps.Count == 0)
            {
                add($"{path}.progressive.steps", "Add at least one step.");
            }

            for (var i = 0; i < progressive.Steps.Count; i++)
            {
                var step = progressive.Steps[i];
                if (step.Percent is < 0 or > 100 || double.IsNaN(step.Percent))
                {
                    add($"{path}.progressive.steps[{i}]", "Percent must be between 0 and 100.");
                }

                if (i > 0 && step.At <= progressive.Steps[i - 1].At)
                {
                    add($"{path}.progressive.steps[{i}]", "Steps must be in time order.");
                }

                if (i > 0 && step.Percent < progressive.Steps[i - 1].Percent)
                {
                    add($"{path}.progressive.steps[{i}]", "A progressive rollout only widens; use the kill switch to go back.");
                }
            }
        }
    }
}
