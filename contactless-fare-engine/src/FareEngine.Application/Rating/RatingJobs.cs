using System.Threading.Channels;
using FareEngine.Application.Persistence;
using Microsoft.EntityFrameworkCore;

namespace FareEngine.Application.Rating;

/// <summary>Wakes the worker early. Losing a signal is harmless: the worker also polls the durable queue.</summary>
public sealed class RatingSignal
{
    private readonly Channel<bool> _channel = Channel.CreateBounded<bool>(
        new BoundedChannelOptions(1) { FullMode = BoundedChannelFullMode.DropWrite });

    public void Notify() => _channel.Writer.TryWrite(true);

    public async Task WaitAsync(TimeSpan atMost, CancellationToken ct)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(atMost);
        try
        {
            _ = await _channel.Reader.ReadAsync(timeout.Token);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            // Time to poll.
        }
    }
}

public sealed class RatingJobs(FareDbContext db)
{
    /// <summary>Adds weeks to the queue, or bumps the revision of ones already there. Joins the caller's transaction.</summary>
    public async Task RequestAsync(IEnumerable<(string Card, DateOnly Week)> weeks, DateTimeOffset dueAt, CancellationToken ct)
    {
        ArgumentNullException.ThrowIfNull(weeks);
        var due = dueAt.ToUnixTimeMilliseconds();
        foreach (var (card, week) in weeks)
        {
            await db.Database.ExecuteSqlAsync(
                $"""
                INSERT INTO Jobs (CardToken, WeekStart, Revision, DueAtMs, Attempts, Dead)
                VALUES ({card}, {week}, 1, {due}, 0, 0)
                ON CONFLICT (CardToken, WeekStart) DO UPDATE
                SET Revision = Revision + 1, DueAtMs = MIN(DueAtMs, excluded.DueAtMs), Attempts = 0, Dead = 0, LastError = NULL
                """,
                ct);
        }
    }

    public Task<List<RatingJob>> DueAsync(DateTimeOffset now, int limit, CancellationToken ct)
    {
        var ms = now.ToUnixTimeMilliseconds();
        return db.Jobs.AsNoTracking()
            .Where(j => !j.Dead && j.DueAtMs <= ms)
            .OrderBy(j => j.DueAtMs).ThenBy(j => j.CardToken).ThenBy(j => j.WeekStart)
            .Take(limit)
            .ToListAsync(ct);
    }
}
