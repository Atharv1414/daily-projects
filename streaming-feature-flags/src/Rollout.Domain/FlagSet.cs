using System.Collections.Frozen;
using System.Text.Json;
using Rollout.Domain.Expressions;

namespace Rollout.Domain;

public enum Reason
{
    /// <summary>The kill switch is off, so the off variant is served.</summary>
    Off,

    /// <summary>A prerequisite flag did not serve the variant this flag needs.</summary>
    PrerequisiteFailed,

    /// <summary>The unit is named in a target list.</summary>
    TargetMatch,

    /// <summary>A targeting rule matched.</summary>
    RuleMatch,

    /// <summary>No rule matched, so the default serve applied.</summary>
    Fallthrough,

    /// <summary>The flag does not exist in this environment; the caller's default should be used.</summary>
    FlagNotFound,
}

/// <summary>The answer for one flag, with enough detail to explain it to a support engineer.</summary>
public sealed record Evaluation(
    string FlagKey,
    string Variant,
    JsonElement? Value,
    Reason Reason,
    string? RuleId = null,
    bool InExperiment = false,
    int? Bucket = null,
    string? FailedPrerequisite = null);

/// <summary>A flag with its rules parsed once, so evaluation never touches the parser.</summary>
public sealed class CompiledFlag
{
    public CompiledFlag(FlagDefinition definition, long version)
    {
        ArgumentNullException.ThrowIfNull(definition);
        Definition = definition;
        Version = version;
        Conditions = [.. definition.RuleList.Select(r => Parser.Parse(r.Condition))];
        VariantValues = definition.Variants.ToFrozenDictionary(v => v.Key, v => v.Value, StringComparer.Ordinal);
        Targeted = definition.TargetLists
            .SelectMany(t => t.UnitKeys.Select(u => (Unit: u, t.Variant)))
            .ToFrozenDictionary(x => x.Unit, x => x.Variant, StringComparer.Ordinal);
    }

    public FlagDefinition Definition { get; }

    public long Version { get; }

    public IReadOnlyList<Node> Conditions { get; }

    public FrozenDictionary<string, JsonElement> VariantValues { get; }

    public FrozenDictionary<string, string> Targeted { get; }
}

/// <summary>
/// An immutable, versioned set of compiled flags for one environment. Readers share it without locks;
/// a write builds a new set and swaps the reference.
/// </summary>
public sealed class FlagSet
{
    public const int MaxPrerequisiteDepth = 10;

    private readonly FrozenDictionary<string, CompiledFlag> _flags;
    private readonly string[] _orderedKeys;

    public FlagSet(IEnumerable<CompiledFlag> flags)
    {
        _flags = flags.ToFrozenDictionary(f => f.Definition.Key, StringComparer.Ordinal);
        _orderedKeys = [.. _flags.Keys.Order(StringComparer.Ordinal)];
    }

    public static FlagSet Compile(IEnumerable<(FlagDefinition Definition, long Version)> flags) =>
        new(flags.Select(f => new CompiledFlag(f.Definition, f.Version)));

    public IEnumerable<CompiledFlag> Flags => _flags.Values;

    public int Count => _flags.Count;

    public bool TryGet(string key, out CompiledFlag flag) => _flags.TryGetValue(key, out flag!);

    public Evaluation Evaluate(string flagKey, EvaluationContext context, DateTimeOffset now)
    {
        ArgumentNullException.ThrowIfNull(context);
        var memo = new Dictionary<string, Evaluation>(StringComparer.Ordinal);
        return Evaluate(flagKey, context, now, memo, depth: 0);
    }

    /// <summary>Evaluates every flag, sharing prerequisite results between them.</summary>
    public IReadOnlyList<Evaluation> EvaluateAll(EvaluationContext context, DateTimeOffset now)
    {
        ArgumentNullException.ThrowIfNull(context);
        var memo = new Dictionary<string, Evaluation>(_flags.Count, StringComparer.Ordinal);
        var results = new Evaluation[_orderedKeys.Length];
        for (var i = 0; i < results.Length; i++)
        {
            results[i] = Evaluate(_orderedKeys[i], context, now, memo, depth: 0);
        }

        return results;
    }

    private Evaluation Evaluate(string key, EvaluationContext context, DateTimeOffset now, Dictionary<string, Evaluation> memo, int depth)
    {
        if (memo.TryGetValue(key, out var cached))
        {
            return cached;
        }

        if (!_flags.TryGetValue(key, out var flag))
        {
            return new Evaluation(key, string.Empty, null, Reason.FlagNotFound);
        }

        var result = EvaluateFlag(flag, context, now, memo, depth);
        memo[key] = result;
        return result;
    }

    private Evaluation EvaluateFlag(CompiledFlag flag, EvaluationContext context, DateTimeOffset now, Dictionary<string, Evaluation> memo, int depth)
    {
        var definition = flag.Definition;
        Evaluation Serve(string variant, Reason reason, string? ruleId = null, bool experiment = false, int? bucket = null, string? failed = null) =>
            new(definition.Key, variant, flag.VariantValues[variant], reason, ruleId, experiment, bucket, failed);

        if (!definition.On)
        {
            return Serve(definition.OffVariant, Reason.Off);
        }

        foreach (var prerequisite in definition.PrerequisiteList)
        {
            // Validation rejects cycles, but a depth cap keeps a bad import from overflowing the stack.
            var parent = depth >= MaxPrerequisiteDepth
                ? null
                : Evaluate(prerequisite.FlagKey, context, now, memo, depth + 1);
            if (parent is null || parent.Reason == Reason.FlagNotFound || parent.Variant != prerequisite.Variant)
            {
                return Serve(definition.OffVariant, Reason.PrerequisiteFailed, failed: prerequisite.FlagKey);
            }
        }

        var unit = context.UnitKey(definition.BucketBy);
        if (unit is not null && flag.Targeted.TryGetValue(unit, out var targeted))
        {
            return Serve(targeted, Reason.TargetMatch);
        }

        for (var i = 0; i < flag.Conditions.Count; i++)
        {
            if (Interpreter.Matches(flag.Conditions[i], context))
            {
                var rule = definition.RuleList[i];
                var (variant, experiment, bucket) = Resolve(rule.Serve, definition, unit, now);
                return Serve(variant, Reason.RuleMatch, rule.Id, experiment, bucket);
            }
        }

        var (fallthrough, inExperiment, b) = Resolve(definition.Fallthrough, definition, unit, now);
        return Serve(fallthrough, Reason.Fallthrough, experiment: inExperiment, bucket: b);
    }

    /// <summary>
    /// Picks a variant for a serve. Without a unit key there is nothing stable to bucket on, so the
    /// unit gets the first rollout variant (or the "from" side of a progressive rollout) and is kept out of results.
    /// </summary>
    public static (string Variant, bool InExperiment, int? Bucket) Resolve(Serve serve, FlagDefinition flag, string? unit, DateTimeOffset now)
    {
        ArgumentNullException.ThrowIfNull(serve);
        ArgumentNullException.ThrowIfNull(flag);
        if (serve.Variant is { } fixedVariant)
        {
            return (fixedVariant, false, null);
        }

        if (serve.Rollout is { } rollout)
        {
            if (unit is null)
            {
                return (rollout[0].Variant, false, null);
            }

            var bucket = Bucketing.Bucket(flag.EffectiveSalt, flag.Key, unit);
            var cumulative = 0;
            foreach (var weighted in rollout)
            {
                cumulative += weighted.Weight;
                if (bucket < cumulative)
                {
                    return (weighted.Variant, true, bucket);
                }
            }

            return (rollout[^1].Variant, true, bucket);
        }

        var progressive = serve.Progressive!;
        if (unit is null)
        {
            return (progressive.From, false, null);
        }

        var b = Bucketing.Bucket(flag.EffectiveSalt, flag.Key, unit);
        var threshold = (int)Math.Round(progressive.PercentAt(now) * (Bucketing.Buckets / 100.0));
        return (b < threshold ? progressive.To : progressive.From, false, b);
    }
}
