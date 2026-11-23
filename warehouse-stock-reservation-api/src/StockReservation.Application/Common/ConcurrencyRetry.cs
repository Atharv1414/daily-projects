using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using StockReservation.Application.Persistence;
using StockReservation.Domain;

namespace StockReservation.Application.Common;

/// <summary>
/// Runs a unit of work that reads, mutates and saves under optimistic concurrency.
/// On a version conflict the change tracker is cleared and the whole unit re-runs against fresh data.
/// </summary>
public static class ConcurrencyRetry
{
    public static async Task<(Result<T> Result, int Retries)> ExecuteAsync<T>(
        StockDbContext db,
        int maxRetries,
        Func<CancellationToken, Task<Result<T>>> work,
        CancellationToken ct)
    {
        for (var attempt = 0; ; attempt++)
        {
            try
            {
                return (await work(ct), attempt);
            }
            catch (DbUpdateConcurrencyException) when (attempt < maxRetries)
            {
                db.ChangeTracker.Clear();
                // Full jitter keeps competing writers from retrying in lock-step.
                var ceilingMs = Math.Min(2 << attempt, 64);
                await Task.Delay(TimeSpan.FromMilliseconds(Random.Shared.Next(0, ceilingMs + 1)), ct);
            }
            catch (DbUpdateConcurrencyException)
            {
                db.ChangeTracker.Clear();
                return (DomainError.Conflict(
                    "concurrency.exhausted",
                    "The stock record kept changing underneath this request; please retry."), attempt);
            }
        }
    }

    /// <summary>True when a save failed because of a UNIQUE constraint (e.g. a duplicate idempotency key).</summary>
    public static bool IsUniqueViolation(DbUpdateException ex) =>
        ex.InnerException is SqliteException { SqliteErrorCode: 19, SqliteExtendedErrorCode: 2067 or 1555 };
}
