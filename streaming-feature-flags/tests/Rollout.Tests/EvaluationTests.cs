using System.Text;
using Rollout.Application;
using Rollout.Domain;

namespace Rollout.Tests;

public class EvaluationTests
{
    private static readonly DateTimeOffset Now = DemoFlags.ReleaseStart.AddDays(5).AddHours(1);

    private static FlagSet Demo(params FlagDefinition[] overrides)
    {
        var flags = DemoFlags.All().ToDictionary(f => f.Key, StringComparer.Ordinal);
        foreach (var flag in overrides)
        {
            flags[flag.Key] = flag;
        }

        return FlagSet.Compile(flags.Values.Select(f => (f, 1L)));
    }

    private static EvaluationContext Viewer(string id, params (string, Value)[] extra) =>
        EvaluationContext.Of([("userId", Value.Of(id)), ("deviceId", Value.Of("device-" + id)), ("householdId", Value.Of("hh-" + id)), .. extra]);

    [Theory]
    [InlineData("", 0u, 0x00000000u)]
    [InlineData("hello", 0u, 0x248bfa47u)]
    [InlineData("The quick brown fox jumps over the lazy dog", 0u, 0x2e4ff723u)]
    [InlineData("abc", 0u, 0xb3dd93fau)]
    [InlineData("", 1u, 0x514e28b7u)]
    public void Murmur3_matches_the_reference_vectors(string input, uint seed, uint expected) =>
        Assert.Equal(expected, Bucketing.Murmur3(Encoding.UTF8.GetBytes(input), seed));

    [Fact]
    public void Buckets_are_stable_and_differ_between_flags()
    {
        var a = Bucketing.Bucket("salt", "flag-a", "user-1");
        Assert.Equal(a, Bucketing.Bucket("salt", "flag-a", "user-1"));
        var differs = Enumerable.Range(0, 200).Count(i =>
            Bucketing.Bucket("flag-a", "flag-a", $"u{i}") / 1000 != Bucketing.Bucket("flag-b", "flag-b", $"u{i}") / 1000);
        Assert.True(differs > 180, "Flags should bucket independently, or every experiment would get the same viewers.");
    }

    [Fact]
    public void Long_unit_keys_use_the_pooled_buffer_and_give_the_same_answer_each_time()
    {
        var key = new string('x', 5_000);
        Assert.Equal(Bucketing.Bucket("s", "f", key), Bucketing.Bucket("s", "f", key));
        Assert.InRange(Bucketing.Bucket("s", "f", key), 0, Bucketing.Buckets - 1);
    }

    [Fact]
    public void Weighted_split_lands_close_to_the_configured_weights()
    {
        var flags = Demo();
        var counts = Enumerable.Range(0, 30_000)
            .Select(i => flags.Evaluate("autoplay.countdown", Viewer($"u{i}"), Now))
            .GroupBy(e => e.Variant)
            .ToDictionary(g => g.Key, g => g.Count());
        foreach (var variant in new[] { "s5", "s10", "s15" })
        {
            Assert.InRange(counts[variant], 9_600, 10_400);
        }
    }

    [Fact]
    public void Progressive_rollout_only_ever_adds_units()
    {
        var player = DemoFlags.NewPlayer();
        var steps = player.Fallthrough.Progressive!.Steps;
        var units = Enumerable.Range(0, 5_000).Select(i => $"device-{i}").ToList();
        HashSet<string> previous = [];
        foreach (var step in steps)
        {
            var on = units.Where(u => FlagSet.Resolve(player.Fallthrough, player, u, step.At).Variant == "on").ToHashSet();
            Assert.Subset(on, previous);
            previous = on;
        }

        Assert.Equal(units.Count, previous.Count);
        Assert.Equal("off", FlagSet.Resolve(player.Fallthrough, player, "device-1", DemoFlags.ReleaseStart.AddMinutes(-1)).Variant);
    }

    [Fact]
    public void Kill_switch_serves_the_off_variant_whatever_the_rules_say()
    {
        var flags = Demo(DemoFlags.DownloadQuality() with { On = false });
        var result = flags.Evaluate("downloads.max-quality", Viewer("u1", ("plan", Value.Of("premium"))), Now);
        Assert.Equal(("sd", Reason.Off), (result.Variant, result.Reason));
    }

    [Fact]
    public void Targets_beat_rules_and_rules_are_tried_in_order()
    {
        var flags = Demo();
        var qa = EvaluationContext.Of(("deviceId", Value.Of("device-qa-02")), ("device.platform", Value.Of("smarttv")), ("device.year", Value.Of(2015)));
        Assert.Equal(Reason.TargetMatch, flags.Evaluate("player.v2", qa, Now).Reason);

        var premium = Viewer("u2", ("plan", Value.Of("premium")), ("appVersion", Value.Of("7.4.0")));
        var result = flags.Evaluate("downloads.max-quality", premium, Now);
        Assert.Equal(("uhd", "premium-new-app"), (result.Variant, result.RuleId));

        var oldApp = Viewer("u3", ("plan", Value.Of("premium")), ("appVersion", Value.Of("7.3.9")));
        Assert.Equal("standard-or-premium", flags.Evaluate("downloads.max-quality", oldApp, Now).RuleId);
    }

    [Fact]
    public void A_failed_prerequisite_serves_off_and_says_which_one()
    {
        var flags = Demo(DemoFlags.KidsProfileLock() with { On = false });
        var result = flags.Evaluate("live.low-latency", Viewer("u4"), Now);
        Assert.Equal(Reason.PrerequisiteFailed, result.Reason);
        Assert.Equal("kids.pin-lock", result.FailedPrerequisite);
        Assert.Equal("off", result.Variant);
    }

    [Fact]
    public void Without_a_bucketing_key_the_unit_is_kept_out_of_the_experiment()
    {
        var flags = Demo();
        var anonymous = EvaluationContext.Of(("country", Value.Of("GB")));
        var result = flags.Evaluate("autoplay.countdown", anonymous, Now);
        Assert.False(result.InExperiment);
        Assert.Equal("s5", result.Variant);
        Assert.Equal(Reason.FlagNotFound, flags.Evaluate("no.such.flag", anonymous, Now).Reason);
        Assert.Null(flags.Evaluate("no.such.flag", anonymous, Now).Value);
    }
}
