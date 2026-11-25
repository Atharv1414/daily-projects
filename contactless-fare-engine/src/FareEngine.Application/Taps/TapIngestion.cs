using FareEngine.Application.Persistence;
using FareEngine.Application.Rating;
using FareEngine.Domain;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace FareEngine.Application.Taps;

public sealed record IncomingTap(Guid Id, string CardToken, string PlaceId, TapKind Kind, DateTimeOffset OccurredAt);

public enum TapOutcome
{
    Accepted,
    Duplicate,
    Conflict,
    Rejected,
}

public sealed record TapResult(Guid Id, TapOutcome Outcome, string? Reason = null);

/// <summary>Stores taps exactly once and asks for the weeks they touch to be rated.</summary>
public sealed partial class TapIngestion(
    FareDbContext db,
    Network network,
    RatingJobs queue,
    RatingSignal signal,
    TimeProvider clock,
    IOptions<FareOptions> options,
    ILogger<TapIngestion> logger)
{
    private readonly FareOptions _options = options.Value;

    public async Task<IReadOnlyList<TapResult>> IngestAsync(
        IReadOnlyList<IncomingTap> taps,
        string submittedBy,
        TapSource source = TapSource.Reader,
        string? reason = null,
        CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(taps);
        if (taps.Count > _options.MaxTapsPerBatch)
        {
            throw new BatchTooLargeException(taps.Count, _options.MaxTapsPerBatch);
        }

        var now = clock.GetUtcNow();
        var results = new TapResult[taps.Count];

        // Begin immediately: two readers retrying the same batch queue up here instead of racing on the check below.
        await using var transaction = await db.Database.BeginTransactionAsync(ct);
        var ids = taps.Select(t => t.Id).Distinct().ToList();
        var known = await db.Taps.AsNoTracking().Where(t => ids.Contains(t.Id)).ToDictionaryAsync(t => t.Id, ct);
        var weeks = new HashSet<(string Card, DateOnly Week)>();
        for (var i = 0; i < taps.Count; i++)
        {
            var tap = taps[i];
            if (Problem(tap, now) is { } problem)
            {
                results[i] = new TapResult(tap.Id, TapOutcome.Rejected, problem);
                continue;
            }

            if (known.TryGetValue(tap.Id, out var existing))
            {
                results[i] = SameTap(existing, tap)
                    ? new TapResult(tap.Id, TapOutcome.Duplicate)
                    : new TapResult(tap.Id, TapOutcome.Conflict, "This tap id was already used for a different tap.");
                continue;
            }

            var record = new TapRecord
            {
                Id = tap.Id,
                CardToken = tap.CardToken,
                PlaceId = tap.PlaceId,
                Kind = tap.Kind,
                OccurredAtMs = tap.OccurredAt.ToUnixTimeMilliseconds(),
                ReceivedAtMs = now.ToUnixTimeMilliseconds(),
                Source = source,
                SubmittedBy = submittedBy,
                Reason = reason,
            };
            db.Taps.Add(record);
            known[tap.Id] = record;
            foreach (var week in WeeksTouched(tap.OccurredAt))
            {
                weeks.Add((tap.CardToken, week));
            }

            results[i] = new TapResult(tap.Id, TapOutcome.Accepted);
        }

        await db.SaveChangesAsync(ct);
        await queue.RequestAsync(weeks, now, ct);
        await transaction.CommitAsync(ct);
        db.ChangeTracker.Clear();
        signal.Notify();
        var accepted = results.Count(r => r.Outcome == TapOutcome.Accepted);
        LogBatch(logger, submittedBy, accepted, taps.Count);
        return results;
    }

    /// <summary>A journey can straddle Monday 04:30, so a tap near the boundary affects both weeks.</summary>
    internal static IEnumerable<DateOnly> WeeksTouched(DateTimeOffset occurredAt) =>
        new[] { -RatingEngine.Margin, TimeSpan.Zero, RatingEngine.Margin }
            .Select(shift => ServiceCalendar.WeekStart(ServiceCalendar.ServiceDate(occurredAt + shift)))
            .Distinct();

    private static bool SameTap(TapRecord a, IncomingTap b) =>
        a.CardToken == b.CardToken
        && a.PlaceId == b.PlaceId
        && a.Kind == b.Kind
        && a.OccurredAtMs == b.OccurredAt.ToUnixTimeMilliseconds();

    private string? Problem(IncomingTap tap, DateTimeOffset now)
    {
        if (tap.Id == Guid.Empty)
        {
            return "A tap needs an id.";
        }

        if (string.IsNullOrWhiteSpace(tap.CardToken) || tap.CardToken.Length > 64)
        {
            return "A card token of 1 to 64 characters is needed.";
        }

        if (tap.PlaceId is null || !network.TryGet(tap.PlaceId, out var place))
        {
            return $"Unknown station or route '{tap.PlaceId}'.";
        }

        if (!Enum.IsDefined(tap.Kind) || (place!.Mode == TravelMode.Bus) != (tap.Kind == TapKind.Board))
        {
            return $"A {tap.Kind} tap is not possible at {place!.Name}.";
        }

        if (tap.OccurredAt > now.AddMinutes(_options.MaxClockSkewMinutes))
        {
            return "The tap is in the future: check the reader's clock.";
        }

        return tap.OccurredAt < now.AddDays(-_options.AcceptTapsForDays)
            ? $"The tap is more than {_options.AcceptTapsForDays} days old."
            : null;
    }

    [LoggerMessage(Level = LogLevel.Information, Message = "{Source} sent {Total} taps, {Accepted} were new")]
    private static partial void LogBatch(ILogger logger, string source, int accepted, int total);
}

public sealed class BatchTooLargeException(int count, int limit)
    : Exception($"A batch may hold {limit} taps; this one has {count}.");
