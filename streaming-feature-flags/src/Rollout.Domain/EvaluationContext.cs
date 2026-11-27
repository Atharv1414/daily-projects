using System.Text.Json;

namespace Rollout.Domain;

/// <summary>
/// What we know about the viewer or device asking for flags. Nested JSON objects are flattened
/// to dotted names, so <c>{"device": {"os": "tvos"}}</c> becomes <c>device.os</c>.
/// </summary>
public sealed class EvaluationContext
{
    public const int MaxAttributes = 64;
    public const int MaxDepth = 4;

    private readonly Dictionary<string, Value> _attributes;

    public EvaluationContext(IReadOnlyDictionary<string, Value> attributes)
    {
        ArgumentNullException.ThrowIfNull(attributes);
        if (attributes.Count > MaxAttributes)
        {
            throw new ArgumentException($"A context may carry at most {MaxAttributes} attributes.", nameof(attributes));
        }

        _attributes = new Dictionary<string, Value>(attributes, StringComparer.Ordinal);
    }

    public IReadOnlyDictionary<string, Value> Attributes => _attributes;

    public Value Get(string name) => _attributes.GetValueOrDefault(name, Value.Null);

    /// <summary>The string used for bucketing, or null when the attribute is missing or empty.</summary>
    public string? UnitKey(string attribute) => Get(attribute) switch
    {
        StringValue { Text.Length: > 0 } s => s.Text,
        NumberValue n => n.Describe(),
        _ => null,
    };

    public static EvaluationContext FromJson(JsonElement json)
    {
        if (json.ValueKind != JsonValueKind.Object)
        {
            throw new ArgumentException("A context must be a JSON object.", nameof(json));
        }

        var attributes = new Dictionary<string, Value>(StringComparer.Ordinal);
        Flatten(json, prefix: null, depth: 0, attributes);
        return new EvaluationContext(attributes);
    }

    public static EvaluationContext Of(params (string Name, Value Value)[] attributes)
    {
        ArgumentNullException.ThrowIfNull(attributes);
        return new EvaluationContext(attributes.ToDictionary(a => a.Name, a => a.Value, StringComparer.Ordinal));
    }

    private static void Flatten(JsonElement json, string? prefix, int depth, Dictionary<string, Value> into)
    {
        if (depth > MaxDepth)
        {
            throw new ArgumentException($"Context objects may nest at most {MaxDepth} levels.", nameof(json));
        }

        foreach (var property in json.EnumerateObject())
        {
            var name = prefix is null ? property.Name : $"{prefix}.{property.Name}";
            if (property.Value.ValueKind == JsonValueKind.Object)
            {
                Flatten(property.Value, name, depth + 1, into);
            }
            else if (property.Value.ValueKind == JsonValueKind.Array
                && property.Value.EnumerateArray().Any(e => e.ValueKind is JsonValueKind.Object or JsonValueKind.Array))
            {
                throw new ArgumentException($"'{name}' must be a list of plain values.", nameof(json));
            }
            else
            {
                into[name] = Value.FromJson(property.Value);
            }

            if (into.Count > MaxAttributes)
            {
                throw new ArgumentException($"A context may carry at most {MaxAttributes} attributes.", nameof(json));
            }
        }
    }
}
