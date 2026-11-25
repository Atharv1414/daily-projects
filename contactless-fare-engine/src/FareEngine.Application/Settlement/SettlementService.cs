using FareEngine.Application.Persistence;
using FareEngine.Domain;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace FareEngine.Application.Settlement;

public sealed record SettlementSummary(
    DateOnly Date, bool AlreadyDone, int Lines, Money Collected, Money Refunded);

/// <summary>
/// Closes a service day: nets every unsettled ledger entry up to it into one bank instruction per card.
/// Late adjustments to days already closed are picked up by the next settlement.
/// </summary>
public sealed partial class SettlementService(
    FareDbContext db, TimeProvider clock, IOptions<FareOptions> options, ILogger<SettlementService> logger)
{
    public async Task<SettlementSummary> SettleAsync(DateOnly date, CancellationToken ct = default)
    {
        var now = clock.GetUtcNow();
        var opensAt = ServiceCalendar.StartOf(date.AddDays(1)).AddHours(options.Value.SettlementGraceHours);
        if (now < opensAt)
        {
            throw new SettlementNotReadyException(date, $"It can be settled from {opensAt:u}.");
        }

        await using var transaction = await db.Database.BeginTransactionAsync(ct);
        if (await db.SettlementRuns.AsNoTracking().FirstOrDefaultAsync(r => r.SettlementDate == date, ct) is { } done)
        {
            return new SettlementSummary(date, true, done.Lines, new Money(done.CollectedPence), new Money(done.RefundedPence));
        }

        var nowMs = now.ToUnixTimeMilliseconds();
        var week = ServiceCalendar.WeekStart(date);
        // A journey still under way may wait; anything due, retrying or parked may not.
        var unrated = await db.Jobs.CountAsync(j => j.WeekStart <= week && (j.DueAtMs <= nowMs || j.Attempts > 0), ct);
        if (unrated > 0)
        {
            throw new SettlementNotReadyException(date, $"{unrated} card weeks are still waiting to be rated.");
        }

        var groups = await db.Ledger
            .Where(e => e.SettlementLineId == null && e.ServiceDate <= date)
            .GroupBy(e => e.CardToken)
            .Select(g => new { Card = g.Key, Amount = g.Sum(e => e.AmountPence), Count = g.Count() })
            .ToListAsync(ct);
        var lines = groups.Select(g => new SettlementLine
        {
            SettlementDate = date,
            CardToken = g.Card,
            AmountPence = g.Amount,
            EntryCount = g.Count,
            CreatedAtMs = nowMs,
        }).ToList();
        db.SettlementLines.AddRange(lines);
        var collected = lines.Where(l => l.AmountPence > 0).Sum(l => l.AmountPence);
        var refunded = -lines.Where(l => l.AmountPence < 0).Sum(l => l.AmountPence);
        db.SettlementRuns.Add(new SettlementRun
        {
            SettlementDate = date,
            Lines = lines.Count,
            CollectedPence = collected,
            RefundedPence = refunded,
            CompletedAtMs = nowMs,
        });
        await db.SaveChangesAsync(ct);

        // One statement links every entry to its card's line.
        await db.Database.ExecuteSqlAsync(
            $"""
            UPDATE Ledger SET SettlementLineId =
                (SELECT l.Id FROM SettlementLines l WHERE l.SettlementDate = {date} AND l.CardToken = Ledger.CardToken)
            WHERE SettlementLineId IS NULL AND ServiceDate <= {date}
            """,
            ct);
        await transaction.CommitAsync(ct);
        db.ChangeTracker.Clear();
        LogSettled(logger, date, lines.Count, collected, refunded);
        return new SettlementSummary(date, false, lines.Count, new Money(collected), new Money(refunded));
    }

    [LoggerMessage(Level = LogLevel.Information, Message = "Settled {Date}: {Lines} cards, {Collected}p collected, {Refunded}p refunded")]
    private static partial void LogSettled(ILogger logger, DateOnly date, int lines, long collected, long refunded);
}

public sealed class SettlementNotReadyException(DateOnly date, string reason)
    : Exception($"{date:yyyy-MM-dd} cannot be settled yet. {reason}");
