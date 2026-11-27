using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Rollout.Application.Persistence;

namespace Rollout.Application.Exposures;

/// <summary>
/// Rolls exposures up into hourly counts and upserts them in one statement per row. Separate from the
/// background service so tests and the benchmark can drain the queue on demand.
/// </summary>
public sealed partial class ExposureFlusher(
    ExposureBuffer queue,
    IServiceScopeFactory scopes,
    IOptions<RolloutOptions> options,
    ILogger<ExposureFlusher> logger)
{
    private readonly int _batchSize = options.Value.ExposureBatchSize;

    /// <summary>Takes whatever is waiting, up to a batch, and writes it. Returns the number of exposures written.</summary>
    public async Task<int> FlushOnceAsync(CancellationToken ct = default)
    {
        var batch = new List<Exposure>(Math.Min(_batchSize, Math.Max(queue.Pending, 1)));
        while (batch.Count < _batchSize && queue.Reader.TryRead(out var exposure))
        {
            batch.Add(exposure);
        }

        if (batch.Count > 0)
        {
            await WriteAsync(batch, ct);
        }

        return batch.Count;
    }

    /// <summary>Flushes until the queue is empty.</summary>
    public async Task<int> DrainAsync(CancellationToken ct = default)
    {
        var total = 0;
        int written;
        while ((written = await FlushOnceAsync(ct)) > 0)
        {
            total += written;
        }

        return total;
    }

    public static IReadOnlyList<ExposureCount> Aggregate(IEnumerable<Exposure> exposures) =>
    [
        .. exposures
            .GroupBy(e => (e.Environment, e.FlagKey, e.Variant, Hour: HourStart(e.At)))
            .Select(g => new ExposureCount
            {
                Environment = g.Key.Environment,
                FlagKey = g.Key.FlagKey,
                Variant = g.Key.Variant,
                HourStartMs = g.Key.Hour,
                Count = g.LongCount(),
            }),
    ];

    public static long HourStartMs(DateTimeOffset at) => HourStart(at);

    private static long HourStart(DateTimeOffset at)
    {
        var ms = at.ToUnixTimeMilliseconds();
        return ms - (ms % 3_600_000);
    }

    private async Task WriteAsync(List<Exposure> batch, CancellationToken ct)
    {
        var rows = Aggregate(batch);
        await using var scope = scopes.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RolloutDbContext>();
        await using var transaction = await db.Database.BeginTransactionAsync(ct);
        foreach (var row in rows)
        {
            // An upsert adds to the existing hour instead of a read-modify-write, so two writers cannot lose counts.
            await db.Database.ExecuteSqlInterpolatedAsync(
                $"""
                INSERT INTO Exposures (Environment, FlagKey, Variant, HourStartMs, Count)
                VALUES ({row.Environment}, {row.FlagKey}, {row.Variant}, {row.HourStartMs}, {row.Count})
                ON CONFLICT (Environment, FlagKey, Variant, HourStartMs) DO UPDATE SET Count = Count + excluded.Count
                """,
                ct);
        }

        await transaction.CommitAsync(ct);
        LogFlushed(logger, batch.Count, rows.Count);
    }

    [LoggerMessage(Level = LogLevel.Debug, Message = "Wrote {Exposures} exposures as {Rows} hourly rows")]
    private static partial void LogFlushed(ILogger logger, int exposures, int rows);
}

/// <summary>Waits for exposures and flushes them in batches, at least every flush interval.</summary>
public sealed partial class ExposureWriter(
    ExposureBuffer queue,
    ExposureFlusher flusher,
    IOptions<RolloutOptions> options,
    TimeProvider clock,
    ILogger<ExposureWriter> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var interval = options.Value.ExposureFlushInterval;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                if (!await queue.Reader.WaitToReadAsync(stoppingToken))
                {
                    break;
                }

                // Give the batch a moment to fill so one write carries many exposures.
                await Task.Delay(interval, clock, stoppingToken);
                await flusher.DrainAsync(stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception e) when (e is DbUpdateException or InvalidOperationException or Microsoft.Data.Sqlite.SqliteException)
            {
                LogFlushFailed(logger, e);
                await Task.Delay(interval, clock, stoppingToken).ConfigureAwait(ConfigureAwaitOptions.SuppressThrowing);
            }
        }

        // Write what is left on shutdown, without the stopping token, so a deploy does not lose the last batch.
        await flusher.DrainAsync(CancellationToken.None);
    }

    [LoggerMessage(Level = LogLevel.Warning, Message = "Exposure flush failed; will retry")]
    private static partial void LogFlushFailed(ILogger logger, Exception error);
}
