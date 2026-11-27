using Microsoft.EntityFrameworkCore;
using Rollout.Application.Flags;
using Rollout.Application.Persistence;
using Rollout.Domain;

namespace Rollout.Application.Exposures;

public sealed record VariantExposure(string Variant, long Exposures, double ObservedShare, double ExpectedShare);

public sealed record ExperimentReport(
    string FlagKey,
    long Version,
    IReadOnlyList<VariantExposure> Variants,
    SrmResult SampleRatio,
    string Verdict);

/// <summary>Compares the traffic each variant actually received with what the flag says it should get.</summary>
public sealed class ExperimentReports(RolloutDbContext db, FlagStore flags)
{
    public async Task<ExperimentReport> ForFlagAsync(string environment, string key, DateTimeOffset? since, CancellationToken ct = default)
    {
        var flag = await flags.GetAsync(environment, key, ct);
        var weights = flag.Definition.Fallthrough.Rollout ?? throw new NotAnExperimentException(key);

        var query = db.Exposures.AsNoTracking().Where(e => e.Environment == environment && e.FlagKey == key);
        if (since is { } from)
        {
            var fromMs = ExposureFlusher.HourStartMs(from);
            query = query.Where(e => e.HourStartMs >= fromMs);
        }

        var counts = await query
            .GroupBy(e => e.Variant)
            .Select(g => new { Variant = g.Key, Count = g.Sum(e => e.Count) })
            .ToDictionaryAsync(x => x.Variant, x => x.Count, StringComparer.Ordinal, ct);

        var observed = weights.Select(w => counts.GetValueOrDefault(w.Variant)).ToList();
        var expected = weights.Select(w => (double)w.Weight).ToList();
        var srm = SampleRatio.Check(observed, expected);
        var total = observed.Sum();
        var variants = weights
            .Select((w, i) => new VariantExposure(
                w.Variant,
                observed[i],
                total == 0 ? 0 : (double)observed[i] / total,
                w.Weight / (double)Bucketing.Buckets))
            .ToList();

        var verdict = total switch
        {
            0 => "No exposures yet.",
            < 1_000 => "Too few exposures to judge; keep collecting.",
            _ when srm.Mismatch => $"Sample ratio mismatch (p = {srm.PValue:0.###e+0}). Do not read the results until the cause is found.",
            _ => $"Traffic matches the configured split (p = {srm.PValue:0.000}).",
        };
        return new ExperimentReport(key, flag.Version, variants, srm, verdict);
    }
}
