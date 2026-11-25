using FareEngine.Application.Persistence;
using FareEngine.Domain;
using Microsoft.EntityFrameworkCore;

namespace FareEngine.Application.Rating;

/// <summary>Rates one card's week from the tap log and appends whatever the ledger is missing.</summary>
public sealed class WeekRater(FareDbContext db, RatingEngine engine, TariffBook tariffs, TimeProvider clock)
{
    public async Task<WeekStatement> PreviewAsync(string cardToken, DateOnly weekStart, CancellationToken ct = default)
    {
        var (from, to) = RatingEngine.TapWindow(weekStart);
        var fromMs = from.ToUnixTimeMilliseconds();
        var toMs = to.ToUnixTimeMilliseconds();
        var taps = await db.Taps.AsNoTracking()
            .Where(t => t.CardToken == cardToken && t.OccurredAtMs >= fromMs && t.OccurredAtMs < toMs)
            .ToListAsync(ct);
        return engine.Rate(cardToken, weekStart, taps.Select(t => t.ToDomain()), clock.GetUtcNow());
    }

    public async Task<int> RateAsync(RatingJob job, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(job);

        // The write lock is taken before anything is read, so two workers cannot both post the same difference.
        await using var transaction = await db.Database.BeginTransactionAsync(ct);
        var claimed = await Pending(job).ExecuteDeleteAsync(ct);
        if (claimed == 0)
        {
            return 0; // another worker did it, or a newer request replaced this one
        }

        var statement = await PreviewAsync(job.CardToken, job.WeekStart, ct);
        var entries = await db.Ledger.AsNoTracking()
            .Where(e => e.CardToken == job.CardToken && e.WeekStart == job.WeekStart)
            .ToListAsync(ct);
        var posted = entries.GroupBy(e => e.ServiceDate)
            .ToDictionary(g => g.Key, g => new Money(g.Sum(e => e.AmountPence)));
        var settled = entries.Where(e => e.SettlementLineId is not null).Select(e => e.ServiceDate).ToHashSet();
        var plan = LedgerPlanner.Plan(statement, posted, settled);
        var now = clock.GetUtcNow();
        db.Ledger.AddRange(plan.Select(p => new LedgerEntry
        {
            CardToken = job.CardToken,
            WeekStart = job.WeekStart,
            ServiceDate = p.ServiceDate,
            AmountPence = p.Amount.Pence,
            Kind = p.Kind,
            PostedAtMs = now.ToUnixTimeMilliseconds(),
        }));
        await db.SaveChangesAsync(ct);

        // A journey still under way becomes a missing exit if nobody taps out, so look again when it would expire.
        var open = statement.Journeys.LastOrDefault(j => j.Journey.Status == JourneyStatus.InProgress);
        if (open is not null)
        {
            var due = open.Journey.StartedAt + tariffs.On(open.Journey.ServiceDate).MaximumJourney + TimeSpan.FromSeconds(1);
            await new RatingJobs(db).RequestAsync([(job.CardToken, job.WeekStart)], due, ct);
        }

        await transaction.CommitAsync(ct);
        db.ChangeTracker.Clear();
        return plan.Count;
    }

    /// <summary>Records a failure and backs off; after too many tries the job is parked for a person to look at.</summary>
    public async Task FailAsync(RatingJob job, Exception error, int maxAttempts, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(job);
        ArgumentNullException.ThrowIfNull(error);
        db.ChangeTracker.Clear();
        var attempts = job.Attempts + 1;
        var retryAt = clock.GetUtcNow().AddSeconds(Math.Pow(2, attempts)).ToUnixTimeMilliseconds();
        var message = error.Message.Length > 400 ? error.Message[..400] : error.Message;
        await Pending(job).ExecuteUpdateAsync(
            s => s.SetProperty(j => j.Attempts, attempts)
                .SetProperty(j => j.DueAtMs, retryAt)
                .SetProperty(j => j.LastError, message)
                .SetProperty(j => j.Dead, attempts >= maxAttempts),
            ct);
    }

    private IQueryable<RatingJob> Pending(RatingJob job) =>
        db.Jobs.Where(j => j.CardToken == job.CardToken && j.WeekStart == job.WeekStart && j.Revision == job.Revision);
}
