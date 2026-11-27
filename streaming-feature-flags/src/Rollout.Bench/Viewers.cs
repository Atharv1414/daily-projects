using Rollout.Domain;

namespace Rollout.Bench;

/// <summary>Seeded synthetic Corvid TV viewers with a realistic mix of platforms, plans and app versions.</summary>
public static class Viewers
{
    private static readonly (string Platform, double Share)[] Platforms =
        [("smarttv", 0.46), ("mobile", 0.31), ("web", 0.15), ("console", 0.08)];

    private static readonly (string Plan, double Share)[] Plans =
        [("basic-ads", 0.38), ("standard", 0.41), ("premium", 0.21)];

    private static readonly string[] AppVersions = ["7.1.2", "7.2.0", "7.3.5", "7.4.0", "7.4.1", "7.5.0-beta.2"];

    public static IReadOnlyList<EvaluationContext> Generate(int count, int seed)
    {
        var random = new Random(seed);
        var viewers = new List<EvaluationContext>(count);
        for (var i = 0; i < count; i++)
        {
            var platform = Pick(random, Platforms);
            var attributes = new Dictionary<string, Value>(StringComparer.Ordinal)
            {
                ["userId"] = Value.Of($"user-{i:D7}"),
                ["householdId"] = Value.Of($"hh-{i / 3:D7}"),
                ["deviceId"] = Value.Of($"device-{seed}-{i:D7}"),
                ["device.platform"] = Value.Of(platform),
                ["device.year"] = Value.Of(platform == "smarttv" ? 2014 + random.Next(12) : 2020 + random.Next(6)),
                ["plan"] = Value.Of(Pick(random, Plans)),
                ["country"] = Value.Of(random.NextDouble() < 0.88 ? "GB" : "IE"),
                ["status"] = Value.Of(random.NextDouble() < 0.12 ? "lapsed" : "active"),
                ["appVersion"] = Value.Of(AppVersions[random.Next(AppVersions.Length)]),
                ["profile.type"] = Value.Of(random.NextDouble() < 0.18 ? "kids" : "adult"),
                ["network"] = Value.Of(platform == "mobile" && random.NextDouble() < 0.4 ? "cellular" : "wifi"),
            };
            viewers.Add(new EvaluationContext(attributes));
        }

        return viewers;
    }

    private static string Pick(Random random, (string Name, double Share)[] options)
    {
        var roll = random.NextDouble();
        foreach (var (name, share) in options)
        {
            if ((roll -= share) < 0)
            {
                return name;
            }
        }

        return options[^1].Name;
    }
}
