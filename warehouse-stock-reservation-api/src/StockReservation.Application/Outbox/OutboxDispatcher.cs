using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using StockReservation.Application.Common;
using StockReservation.Application.Persistence;
using StockReservation.Domain;

namespace StockReservation.Application.Outbox;

public sealed record DispatchSummary(int Published, int Failed, int DeadLettered);

public sealed record OutboxStats(int Pending, int Published, int DeadLettered, DateTimeOffset? OldestPendingAt);

/// <summary>
/// Publishes pending outbox messages in commit order with at-least-once delivery.
/// A failed message is retried with exponential backoff and dead-lettered after the configured attempts.
/// </summary>
public sealed partial class OutboxDispatcher(
    StockDbContext db,
    IEventPublisher publisher,
    TimeProvider clock,
    IOptions<WorkerOptions> options,
    ILogger<OutboxDispatcher> logger)
{
    public async Task<DispatchSummary> DispatchBatchAsync(CancellationToken ct)
    {
        var opts = options.Value;
        var now = clock.GetUtcNow();
        var batch = await db.Outbox
            .Where(m => m.Status == OutboxStatus.Pending && m.NextAttemptAt <= now)
            .OrderBy(m => m.OccurredAt)
            .Take(opts.BatchSize)
            .ToListAsync(ct);

        int published = 0, failed = 0, dead = 0;
        foreach (var message in batch)
        {
            try
            {
                await publisher.PublishAsync(message, ct);
                message.MarkPublished(clock.GetUtcNow());
                published++;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                message.MarkFailed(
                    ex.Message,
                    clock.GetUtcNow(),
                    opts.OutboxMaxAttempts,
                    TimeSpan.FromSeconds(opts.OutboxBaseRetrySeconds));
                if (message.Status == OutboxStatus.DeadLettered)
                {
                    dead++;
                    LogDeadLettered(logger, message.Id, message.Type, message.Attempts, ex.Message);
                }
                else
                {
                    failed++;
                }
            }
        }

        // Saved once per batch: a crash before this line re-publishes the batch (at-least-once),
        // which is why consumers must de-duplicate on the message id.
        await db.SaveChangesAsync(ct);
        return new DispatchSummary(published, failed, dead);
    }

    public async Task<OutboxStats> GetStatsAsync(CancellationToken ct)
    {
        var counts = await db.Outbox
            .GroupBy(m => m.Status)
            .Select(g => new { Status = g.Key, Count = g.Count() })
            .ToListAsync(ct);
        var oldest = await db.Outbox
            .Where(m => m.Status == OutboxStatus.Pending)
            .OrderBy(m => m.OccurredAt)
            .Select(m => (DateTimeOffset?)m.OccurredAt)
            .FirstOrDefaultAsync(ct);
        int Count(OutboxStatus s) => counts.FirstOrDefault(c => c.Status == s)?.Count ?? 0;
        return new OutboxStats(
            Count(OutboxStatus.Pending),
            Count(OutboxStatus.Published),
            Count(OutboxStatus.DeadLettered),
            oldest);
    }

    [LoggerMessage(
        Level = LogLevel.Error,
        Message = "Outbox message {MessageId} ({EventType}) dead-lettered after {Attempts} attempts: {Error}")]
    private static partial void LogDeadLettered(ILogger logger, Guid messageId, string eventType, int attempts, string error);
}
