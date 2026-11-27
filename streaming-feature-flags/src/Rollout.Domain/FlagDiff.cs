using System.Text.Json;

namespace Rollout.Domain;

/// <summary>Human-readable summary of what changed between two versions of a flag, for the audit log.</summary>
public static class FlagDiff
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public static IReadOnlyList<string> Describe(FlagDefinition? before, FlagDefinition after)
    {
        ArgumentNullException.ThrowIfNull(after);
        if (before is null)
        {
            return [$"Created with {after.Variants.Count} variants, {after.RuleList.Count} rules, {(after.On ? "on" : "off")}."];
        }

        var changes = new List<string>();
        if (before.On != after.On)
        {
            changes.Add(after.On ? "Turned on." : "Turned off (kill switch).");
        }

        if (before.OffVariant != after.OffVariant)
        {
            changes.Add($"Off variant {before.OffVariant} -> {after.OffVariant}.");
        }

        var beforeVariants = before.Variants.Select(v => v.Key).ToHashSet(StringComparer.Ordinal);
        var afterVariants = after.Variants.Select(v => v.Key).ToHashSet(StringComparer.Ordinal);
        changes.AddRange(afterVariants.Except(beforeVariants).Order(StringComparer.Ordinal).Select(v => $"Added variant {v}."));
        changes.AddRange(beforeVariants.Except(afterVariants).Order(StringComparer.Ordinal).Select(v => $"Removed variant {v}."));

        if (!Same(before.Fallthrough, after.Fallthrough))
        {
            changes.Add($"Default serve {Summarise(before.Fallthrough)} -> {Summarise(after.Fallthrough)}.");
        }

        var beforeRules = before.RuleList.ToDictionary(r => r.Id, StringComparer.Ordinal);
        var afterRules = after.RuleList.ToDictionary(r => r.Id, StringComparer.Ordinal);
        foreach (var rule in after.RuleList)
        {
            if (!beforeRules.TryGetValue(rule.Id, out var old))
            {
                changes.Add($"Added rule {rule.Id}: {rule.Condition}.");
            }
            else if (old.Condition != rule.Condition || !Same(old.Serve, rule.Serve))
            {
                changes.Add($"Changed rule {rule.Id}.");
            }
        }

        changes.AddRange(before.RuleList.Where(r => !afterRules.ContainsKey(r.Id)).Select(r => $"Removed rule {r.Id}."));
        if (!before.RuleList.Select(r => r.Id).Where(afterRules.ContainsKey)
                .SequenceEqual(after.RuleList.Select(r => r.Id).Where(beforeRules.ContainsKey)))
        {
            changes.Add("Reordered rules.");
        }

        var beforeTargets = before.TargetLists.Sum(t => t.UnitKeys.Count);
        var afterTargets = after.TargetLists.Sum(t => t.UnitKeys.Count);
        if (!Same(before.TargetLists, after.TargetLists))
        {
            changes.Add($"Target lists changed ({beforeTargets} -> {afterTargets} units).");
        }

        if (!Same(before.PrerequisiteList, after.PrerequisiteList))
        {
            changes.Add("Prerequisites changed.");
        }

        if (before.EffectiveSalt != after.EffectiveSalt || before.BucketBy != after.BucketBy)
        {
            changes.Add("Bucketing changed: every unit may move variant.");
        }

        if (changes.Count == 0 && !Same(before, after))
        {
            changes.Add("Description, tags or variant values changed.");
        }

        return changes;
    }

    private static bool Same<T>(T a, T b) =>
        JsonSerializer.Serialize(a, Json) == JsonSerializer.Serialize(b, Json);

    private static string Summarise(Serve serve) =>
        serve.Variant ?? (serve.Rollout is { } r
            ? "split " + string.Join("/", r.Select(w => $"{w.Variant} {w.Weight / 1000.0:0.###}%"))
            : $"progressive {serve.Progressive!.From} -> {serve.Progressive.To}");
}
