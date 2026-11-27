using System.Text.Json;
using Rollout.Domain;

namespace Rollout.Application;

/// <summary>
/// Flags for Corvid TV, an invented UK streaming service, used by the demo, the benchmark and the tests.
/// They cover each way of serving: a kill switch, rules, a weighted experiment, a progressive release and a prerequisite.
/// </summary>
public static class DemoFlags
{
    /// <summary>The progressive rollout of the new player starts on this date; the benchmark and tests use it as "now".</summary>
    public static readonly DateTimeOffset ReleaseStart = new(2026, 11, 23, 9, 0, 0, TimeSpan.Zero);

    public static IReadOnlyList<FlagDefinition> All() =>
    [
        NewPlayer(),
        AutoplayCountdown(),
        DownloadQuality(),
        AdTierBanner(),
        KidsProfileLock(),
        LiveSportLowLatency(),
    ];

    /// <summary>A rewritten video player, released to 1%, 5%, 25%, 50% and then everyone over a fortnight.</summary>
    public static FlagDefinition NewPlayer() => FlagDefinition.Boolean(
            "player.v2",
            on: true,
            new Serve(Progressive: new ProgressiveRollout("off", "on",
            [
                new RolloutStep(ReleaseStart, 1),
                new RolloutStep(ReleaseStart.AddDays(2), 5),
                new RolloutStep(ReleaseStart.AddDays(5), 25),
                new RolloutStep(ReleaseStart.AddDays(9), 50),
                new RolloutStep(ReleaseStart.AddDays(14), 100),
            ])),
            "The rebuilt video player with adaptive bitrate v2.") with
    {
        BucketBy = "deviceId",
        Targets = [new TargetList("on", ["device-qa-01", "device-qa-02", "device-qa-03"])],
        Rules =
        [
            new Rule("old-tvs", "device.platform == \"smarttv\" and device.year < 2019", Serve.Fixed("off"),
                "2018-and-older smart TVs cannot decode the new manifests."),
            new Rule("staff", "email endsWith \"@corvid.example\"", Serve.Fixed("on")),
        ],
        Tags = ["player", "release"],
    };

    /// <summary>An A/B/C test on the countdown before the next episode starts.</summary>
    public static FlagDefinition AutoplayCountdown() => new(
        "autoplay.countdown",
        FlagKind.Multivariate,
        [Variant("s5", 5), Variant("s10", 10), Variant("s15", 15)],
        OffVariant: "s10",
        Fallthrough: Serve.Split(new("s5", 33_334), new("s10", 33_333), new("s15", 33_333)),
        On: true,
        Description: "Seconds of countdown before the next episode autoplays.",
        Rules: [new Rule("kids", "profile.type == \"kids\"", Serve.Fixed("s15"), "Kids' profiles always get the longest countdown.")],
        Tags: ["experiment", "engagement"]);

    /// <summary>Which download quality to offer, by plan and by app version.</summary>
    public static FlagDefinition DownloadQuality() => new(
        "downloads.max-quality",
        FlagKind.Multivariate,
        [Variant("sd", "576p"), Variant("hd", "1080p"), Variant("uhd", "2160p")],
        OffVariant: "sd",
        Fallthrough: Serve.Fixed("sd"),
        On: true,
        Rules:
        [
            new Rule("premium-new-app", "plan == \"premium\" and semver(appVersion) >= semver(\"7.4.0\")", Serve.Fixed("uhd")),
            new Rule("standard-or-premium", "plan in [\"standard\", \"premium\"]", Serve.Fixed("hd")),
        ],
        Tags: ["downloads"]);

    /// <summary>An upsell banner for the ad-supported tier. Off in Ireland while pricing is agreed.</summary>
    public static FlagDefinition AdTierBanner() => FlagDefinition.Boolean(
            "home.ad-tier-banner",
            on: true,
            Serve.Fixed("off"),
            "Banner offering the £5.99 ad-supported plan to lapsed subscribers.") with
    {
        Rules = [new Rule("lapsed-gb", "country == \"GB\" and status == \"lapsed\" and not plan == \"basic-ads\"", Serve.Fixed("on"))],
        Tags = ["growth"],
    };

    /// <summary>Parental PIN on kids' profiles; must be on before the kids' home page redesign can show.</summary>
    public static FlagDefinition KidsProfileLock() => FlagDefinition.Boolean(
            "kids.pin-lock",
            on: true,
            Serve.Fixed("on"),
            "Ask for the account PIN when leaving a kids' profile.") with
    {
        BucketBy = "householdId",
        Tags = ["safety"],
    };

    /// <summary>Low-latency streams for live football, only once the PIN lock is on, and split 50/50 to measure rebuffering.</summary>
    public static FlagDefinition LiveSportLowLatency() => FlagDefinition.Boolean(
            "live.low-latency",
            on: true,
            Serve.Split(new("on", 50_000), new("off", 50_000)),
            "Low-latency HLS for live sport.") with
    {
        Prerequisites = [new Prerequisite("kids.pin-lock", "on")],
        Rules = [new Rule("no-cellular", "network == \"cellular\"", Serve.Fixed("off"))],
        Tags = ["experiment", "live"],
    };

    private static Variant Variant<T>(string key, T value) => new(key, JsonSerializer.SerializeToElement(value));
}
