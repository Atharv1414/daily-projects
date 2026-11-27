using System.Text.Json;

namespace Rollout.Domain;

public enum FlagKind
{
    /// <summary>Exactly two variants, "on" and "off", with JSON true and false values.</summary>
    Boolean,

    /// <summary>Any number of named variants, each with a JSON value (a string, a number or a small object).</summary>
    Multivariate,
}

/// <summary>One named outcome of a flag.</summary>
public sealed record Variant(string Key, JsonElement Value, string? Description = null);

/// <summary>Share of traffic, in buckets of 1/100,000.</summary>
public sealed record WeightedVariant(string Variant, int Weight);

/// <summary>From <see cref="At"/> onwards, <see cref="Percent"/> of units receive the new variant.</summary>
public sealed record RolloutStep(DateTimeOffset At, double Percent);

/// <summary>A release that widens over time without anyone touching it. Units that have moved stay moved.</summary>
public sealed record ProgressiveRollout(string From, string To, IReadOnlyList<RolloutStep> Steps)
{
    public double PercentAt(DateTimeOffset now) =>
        Steps.LastOrDefault(s => s.At <= now)?.Percent ?? 0;
}

/// <summary>What to serve. Exactly one of the three is set.</summary>
public sealed record Serve(
    string? Variant = null,
    IReadOnlyList<WeightedVariant>? Rollout = null,
    ProgressiveRollout? Progressive = null)
{
    public static Serve Fixed(string variant) => new(Variant: variant);

    public static Serve Split(params WeightedVariant[] weights) => new(Rollout: weights);

    public IEnumerable<string> ReferencedVariants() =>
        Variant is not null ? [Variant]
        : Rollout is not null ? Rollout.Select(w => w.Variant)
        : Progressive is not null ? [Progressive.From, Progressive.To]
        : [];
}

/// <summary>A flag must be serving a given variant for this flag to apply its rules.</summary>
public sealed record Prerequisite(string FlagKey, string Variant);

/// <summary>Named units, such as internal testers' accounts, that always get one variant.</summary>
public sealed record TargetList(string Variant, IReadOnlyList<string> UnitKeys);

/// <summary>A targeting rule. Rules are tried in order and the first match wins.</summary>
public sealed record Rule(string Id, string Condition, Serve Serve, string? Description = null);

/// <summary>The whole definition of one flag in one environment, as authored.</summary>
public sealed record FlagDefinition(
    string Key,
    FlagKind Kind,
    IReadOnlyList<Variant> Variants,
    string OffVariant,
    Serve Fallthrough,
    bool On = false,
    string Description = "",
    IReadOnlyList<Prerequisite>? Prerequisites = null,
    IReadOnlyList<TargetList>? Targets = null,
    IReadOnlyList<Rule>? Rules = null,
    string? Salt = null,
    string BucketBy = "userId",
    IReadOnlyList<string>? Tags = null)
{
    public IReadOnlyList<Prerequisite> PrerequisiteList => Prerequisites ?? [];

    public IReadOnlyList<TargetList> TargetLists => Targets ?? [];

    public IReadOnlyList<Rule> RuleList => Rules ?? [];

    /// <summary>The salt defaults to the key, so renaming a flag (a new key) reshuffles its buckets.</summary>
    public string EffectiveSalt => string.IsNullOrEmpty(Salt) ? Key : Salt;

    public static FlagDefinition Boolean(string key, bool on, Serve fallthrough, string description = "") => new(
        key,
        FlagKind.Boolean,
        [new Variant("on", JsonSerializer.SerializeToElement(true)), new Variant("off", JsonSerializer.SerializeToElement(false))],
        OffVariant: "off",
        Fallthrough: fallthrough,
        On: on,
        Description: description);
}
