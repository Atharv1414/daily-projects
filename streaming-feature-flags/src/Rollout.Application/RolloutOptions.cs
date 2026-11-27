using System.ComponentModel.DataAnnotations;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Rollout.Application;

public sealed class RolloutOptions
{
    public const string Section = "Rollout";

    /// <summary>Environments are fixed by configuration: a typo in a URL must not create a new one.</summary>
    [MinLength(1)]
    public IList<string> Environments { get; init; } = ["development", "staging", "production"];

    [Range(100, 1_000_000)]
    public int ExposureBufferCapacity { get; init; } = 50_000;

    [Range(1, 10_000)]
    public int ExposureBatchSize { get; init; } = 1_000;

    [Range(typeof(TimeSpan), "00:00:00.010", "00:05:00")]
    public TimeSpan ExposureFlushInterval { get; init; } = TimeSpan.FromSeconds(2);

    [Range(1, 500)]
    public int MaxPageSize { get; init; } = 100;

    [Range(1, 10_000)]
    public int MaxExposuresPerRequest { get; init; } = 1_000;
}

/// <summary>One JSON shape everywhere: the API, the database and the audit log.</summary>
public static class FlagJson
{
    public static readonly JsonSerializerOptions Options = Create();

    private static JsonSerializerOptions Create()
    {
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web)
        {
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        };
        options.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.CamelCase));
        options.MakeReadOnly(populateMissingResolver: true);
        return options;
    }
}
