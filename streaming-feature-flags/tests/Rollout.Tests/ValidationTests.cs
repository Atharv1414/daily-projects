using Rollout.Application;
using Rollout.Domain;

namespace Rollout.Tests;

public class ValidationTests
{
    [Fact]
    public void Every_demo_flag_is_valid()
    {
        foreach (var flag in DemoFlags.All())
        {
            Assert.Empty(FlagValidator.Validate(flag));
        }
    }

    [Theory]
    [InlineData(50_000, 40_000, "add up to 100,000")]
    [InlineData(-1, 100_001, "cannot be negative")]
    public void Split_weights_must_cover_exactly_all_buckets(int a, int b, string message)
    {
        var flag = FlagDefinition.Boolean("test.flag", true, Serve.Split(new("on", a), new("off", b)));
        Assert.Contains(FlagValidator.Validate(flag), e => e.Message.Contains(message, StringComparison.Ordinal));
    }

    [Fact]
    public void Broken_definitions_report_every_problem_with_a_path()
    {
        var flag = new FlagDefinition(
            "Bad Key!",
            FlagKind.Boolean,
            [new Variant("on", System.Text.Json.JsonSerializer.SerializeToElement(1))],
            OffVariant: "nope",
            Fallthrough: new Serve(Variant: "on", Rollout: [new WeightedVariant("on", 100_000)]),
            Rules: [new Rule("r1", "plan ==", Serve.Fixed("ghost")), new Rule("r1", "true", Serve.Fixed("on"))]);
        var paths = FlagValidator.Validate(flag).Select(e => e.Path).ToList();
        Assert.Contains("key", paths);
        Assert.Contains("variants", paths);
        Assert.Contains("offVariant", paths);
        Assert.Contains("fallthrough", paths);
        Assert.Contains("rules", paths);
        Assert.Contains("rules[0].condition", paths);
        Assert.Contains("rules[0].serve", paths);
    }

    [Fact]
    public void Progressive_rollouts_cannot_shrink_or_go_back_in_time()
    {
        var t = DemoFlags.ReleaseStart;
        var flag = FlagDefinition.Boolean("test.flag", true, new Serve(Progressive: new ProgressiveRollout("off", "on",
            [new RolloutStep(t, 20), new RolloutStep(t.AddDays(1), 10), new RolloutStep(t.AddDays(1), 30), new RolloutStep(t.AddDays(2), 130)])));
        var messages = FlagValidator.Validate(flag).Select(e => e.Message).ToList();
        Assert.Contains(messages, m => m.Contains("only widens", StringComparison.Ordinal));
        Assert.Contains(messages, m => m.Contains("time order", StringComparison.Ordinal));
        Assert.Contains(messages, m => m.Contains("between 0 and 100", StringComparison.Ordinal));
    }

    [Fact]
    public void Prerequisite_cycles_are_found_and_named()
    {
        var a = FlagDefinition.Boolean("flag-a", true, Serve.Fixed("on")) with { Prerequisites = [new("flag-b", "on")] };
        var b = FlagDefinition.Boolean("flag-b", true, Serve.Fixed("on")) with { Prerequisites = [new("flag-c", "on")] };
        var c = FlagDefinition.Boolean("flag-c", true, Serve.Fixed("on")) with { Prerequisites = [new("flag-a", "on")] };
        var others = new Dictionary<string, FlagDefinition> { ["flag-a"] = a, ["flag-b"] = b };
        var error = Assert.Single(FlagValidator.ValidateInSet(c, others));
        Assert.Contains("flag-c -> flag-a -> flag-b -> flag-c", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Prerequisites_must_exist_and_name_a_real_variant()
    {
        var child = FlagDefinition.Boolean("child", true, Serve.Fixed("on")) with
        {
            Prerequisites = [new("missing", "on"), new("parent", "maybe")],
        };
        var parent = FlagDefinition.Boolean("parent", true, Serve.Fixed("on"));
        var errors = FlagValidator.ValidateInSet(child, new Dictionary<string, FlagDefinition> { ["parent"] = parent });
        Assert.Equal(2, errors.Count);
    }

    [Fact]
    public void Diff_describes_changes_in_plain_words()
    {
        var before = DemoFlags.AutoplayCountdown();
        var after = before with
        {
            On = false,
            Rules = [new Rule("tv", "device.platform == \"smarttv\"", Serve.Fixed("s15"))],
            Fallthrough = Serve.Split(new("s5", 50_000), new("s10", 0), new("s15", 50_000)),
        };
        var changes = FlagDiff.Describe(before, after);
        Assert.Contains("Turned off (kill switch).", changes);
        Assert.Contains(changes, c => c.StartsWith("Added rule tv", StringComparison.Ordinal));
        Assert.Contains("Removed rule kids.", changes);
        Assert.Contains(changes, c => c.StartsWith("Default serve split s5 33.334%", StringComparison.Ordinal));
    }
}
