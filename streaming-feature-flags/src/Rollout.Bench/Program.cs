using System.Diagnostics;
using System.Globalization;
using Rollout.Application;
using Rollout.Bench;
using Rollout.Domain;
using Rollout.Domain.Expressions;

// Usage: dotnet run -c Release --project src/Rollout.Bench -- [viewers] [seed]
var count = args.Length > 0 ? int.Parse(args[0], CultureInfo.InvariantCulture) : 200_000;
var seed = args.Length > 1 ? int.Parse(args[1], CultureInfo.InvariantCulture) : 42;
var flags = FlagSet.Compile(DemoFlags.All().Select(f => (f, 1L)));
var now = DemoFlags.ReleaseStart.AddDays(5).AddHours(1);
var viewers = Viewers.Generate(count, seed);

Console.WriteLine($"Corvid TV flag service benchmark: {count:N0} synthetic viewers, seed {seed}, {flags.Count} flags");
Console.WriteLine();

// 1. Evaluation throughput, single thread and all cores.
for (var warm = 0; warm < 2; warm++)
{
    foreach (var v in viewers.Take(10_000))
    {
        _ = flags.EvaluateAll(v, now);
    }
}

var timer = Stopwatch.StartNew();
long evaluations = 0;
foreach (var viewer in viewers)
{
    evaluations += flags.EvaluateAll(viewer, now).Count;
}

timer.Stop();
var singleNs = timer.Elapsed.TotalNanoseconds / evaluations;
timer.Restart();
var parallelEvaluations = 0L;
Parallel.ForEach(viewers, () => 0L, (v, _, local) => local + flags.EvaluateAll(v, now).Count,
    local => Interlocked.Add(ref parallelEvaluations, local));
timer.Stop();
var parallelPerSecond = parallelEvaluations / timer.Elapsed.TotalSeconds;
Console.WriteLine("Evaluation");
Console.WriteLine($"  single thread      {singleNs,8:N0} ns per flag   ({1e9 / singleNs / 1e6:N2} M flags/s)");
Console.WriteLine($"  {Environment.ProcessorCount,2} threads         {1e9 / parallelPerSecond,8:N0} ns per flag   ({parallelPerSecond / 1e6:N2} M flags/s)");

// 2. Parsing cost, paid once per snapshot build rather than per request.
const string rule = "plan == \"premium\" and semver(appVersion) >= semver(\"7.4.0\") and country in [\"GB\", \"IE\"] and not status == \"lapsed\"";
timer.Restart();
for (var i = 0; i < 100_000; i++)
{
    _ = Parser.Parse(rule);
}

timer.Stop();
Console.WriteLine($"  rule parse         {timer.Elapsed.TotalNanoseconds / 100_000,8:N0} ns per rule (once per snapshot, not per request)");
Console.WriteLine();

// 3. Bucketing uniformity over 20 equal bins.
var bins = new long[20];
foreach (var viewer in viewers)
{
    bins[Bucketing.Bucket("bench", "uniformity", viewer.UnitKey("userId")!) * bins.Length / Bucketing.Buckets]++;
}

var uniform = SampleRatio.Check(bins, [.. Enumerable.Repeat(1.0, bins.Length)]);
Console.WriteLine("Bucketing (MurmurHash3, 100,000 buckets)");
Console.WriteLine($"  20 bins: min {bins.Min():N0}, max {bins.Max():N0}, chi-square {uniform.ChiSquare:N1} on {uniform.DegreesOfFreedom} df, p = {uniform.PValue:0.000}");

// 4. Progressive rollout: every step widens, and nobody who got the new player loses it.
var player = DemoFlags.NewPlayer();
Console.WriteLine();
Console.WriteLine("Progressive rollout of player.v2 (excluding the old-TV rule and staff)");
var previouslyOn = new HashSet<string>(StringComparer.Ordinal);
var movedBack = 0;
foreach (var step in player.Fallthrough.Progressive!.Steps)
{
    var on = new HashSet<string>(StringComparer.Ordinal);
    foreach (var viewer in viewers)
    {
        var unit = viewer.UnitKey(player.BucketBy)!;
        if (FlagSet.Resolve(player.Fallthrough, player, unit, step.At).Variant == "on")
        {
            on.Add(unit);
        }
    }

    movedBack += previouslyOn.Count(u => !on.Contains(u));
    Console.WriteLine($"  {step.At:dd MMM}  target {step.Percent,5:0.#}%  actual {100.0 * on.Count / viewers.Count,6:0.00}%  ({on.Count:N0} devices)");
    previouslyOn = on;
}

Console.WriteLine($"  devices that went back to the old player at a later step: {movedBack}");

// 5. A/B/C test on autoplay.countdown, then the same test with a bug that loses 3% of s15 exposures.
var counts = new Dictionary<string, long>(StringComparer.Ordinal) { ["s5"] = 0, ["s10"] = 0, ["s15"] = 0 };
var lossy = new Dictionary<string, long>(counts, StringComparer.Ordinal);
var drop = new Random(seed + 1);
foreach (var viewer in viewers)
{
    var result = flags.Evaluate("autoplay.countdown", viewer, now);
    if (!result.InExperiment)
    {
        continue;
    }

    counts[result.Variant]++;
    if (result.Variant != "s15" || drop.NextDouble() >= 0.03)
    {
        lossy[result.Variant]++;
    }
}

double[] shares = [33_334, 33_333, 33_333];
var healthy = SampleRatio.Check([counts["s5"], counts["s10"], counts["s15"]], shares);
var broken = SampleRatio.Check([lossy["s5"], lossy["s10"], lossy["s15"]], shares);
Console.WriteLine();
Console.WriteLine("Sample ratio mismatch check on autoplay.countdown (kids' profiles are excluded by a rule)");
Console.WriteLine($"  healthy:      s5 {counts["s5"]:N0} / s10 {counts["s10"]:N0} / s15 {counts["s15"]:N0}  p = {healthy.PValue:0.000}  mismatch: {healthy.Mismatch}");
Console.WriteLine($"  3% s15 loss:  s5 {lossy["s5"]:N0} / s10 {lossy["s10"]:N0} / s15 {lossy["s15"]:N0}  p = {broken.PValue:0.0e+0}  mismatch: {broken.Mismatch}");

// 6. What a few viewers see, with reasons.
Console.WriteLine();
Console.WriteLine("Sample evaluations (first viewer)");
foreach (var evaluation in flags.EvaluateAll(viewers[0], now))
{
    var detail = evaluation.RuleId is null ? string.Empty : $" ({evaluation.RuleId})";
    Console.WriteLine($"  {evaluation.FlagKey,-24} {evaluation.Variant,-5} {evaluation.Reason}{detail}");
}
