using System.Collections.Immutable;
using System.Globalization;
using System.Text.Json;

namespace Rollout.Domain;

/// <summary>
/// A value seen by targeting rules: a context attribute, a literal or the result of a function.
/// Kept deliberately small so that every comparison has one obvious meaning.
/// </summary>
public abstract record Value
{
    public static readonly Value Null = new NullValue();

    public static Value Of(string text) => new StringValue(text);

    public static Value Of(double number) => new NumberValue(number);

    public static Value Of(bool flag) => flag ? BoolValue.True : BoolValue.False;

    public static Value Of(IEnumerable<Value> items) => new ListValue([.. items]);

    /// <summary>Converts a JSON element. Objects are rejected here; callers flatten them first.</summary>
    public static Value FromJson(JsonElement element) => element.ValueKind switch
    {
        JsonValueKind.String => Of(element.GetString()!),
        JsonValueKind.Number => Of(element.GetDouble()),
        JsonValueKind.True => BoolValue.True,
        JsonValueKind.False => BoolValue.False,
        JsonValueKind.Null or JsonValueKind.Undefined => Null,
        JsonValueKind.Array => Of(element.EnumerateArray().Select(FromJson)),
        _ => throw new ArgumentException("Nested objects must be flattened before conversion.", nameof(element)),
    };

    public abstract string Describe();
}

public sealed record NullValue : Value
{
    public override string Describe() => "null";
}

public sealed record StringValue(string Text) : Value
{
    public override string Describe() => JsonSerializer.Serialize(Text);
}

public sealed record NumberValue(double Number) : Value
{
    public override string Describe() => Number.ToString("R", CultureInfo.InvariantCulture);
}

public sealed record BoolValue(bool Flag) : Value
{
    public static readonly BoolValue True = new(true);
    public static readonly BoolValue False = new(false);

    public override string Describe() => Flag ? "true" : "false";
}

/// <summary>A semantic version such as 5.12.0. Pre-release tags sort before the release.</summary>
public sealed record VersionValue(SemVer Version) : Value
{
    public override string Describe() => $"semver(\"{Version}\")";
}

public sealed record ListValue(ImmutableArray<Value> Items) : Value
{
    public bool Equals(ListValue? other) => other is not null && Items.SequenceEqual(other.Items);

    public override int GetHashCode() => Items.Aggregate(17, (h, v) => HashCode.Combine(h, v));

    public override string Describe() => "[" + string.Join(", ", Items.Select(i => i.Describe())) + "]";
}
