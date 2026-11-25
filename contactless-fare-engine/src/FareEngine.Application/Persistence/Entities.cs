using FareEngine.Domain;

namespace FareEngine.Application.Persistence;

/// <summary>An append-only record of a tap. The primary key is the reader's tap id, which makes ingestion idempotent.</summary>
public sealed class TapRecord
{
    public Guid Id { get; init; }

    public required string CardToken { get; init; }

    public required string PlaceId { get; init; }

    public TapKind Kind { get; init; }

    public long OccurredAtMs { get; init; }

    public long ReceivedAtMs { get; init; }

    public TapSource Source { get; init; }

    public required string SubmittedBy { get; init; }

    public string? Reason { get; init; }

    public Tap ToDomain() =>
        new(Id, CardToken, PlaceId, Kind, DateTimeOffset.FromUnixTimeMilliseconds(OccurredAtMs), Source);
}

/// <summary>
/// "This card's week needs rating." Written in the same transaction as the taps, so a crash cannot lose it.
/// <see cref="Revision"/> goes up on every request, so a worker only clears the work it actually saw.
/// </summary>
public sealed class RatingJob
{
    public required string CardToken { get; init; }

    public DateOnly WeekStart { get; init; }

    public long Revision { get; set; }

    public long DueAtMs { get; set; }

    public int Attempts { get; set; }

    public string? LastError { get; set; }

    public bool Dead { get; set; }
}

/// <summary>Append-only money movements. The balance is always the sum of these rows.</summary>
public sealed class LedgerEntry
{
    public long Id { get; init; }

    public required string CardToken { get; init; }

    public DateOnly WeekStart { get; init; }

    public DateOnly ServiceDate { get; init; }

    public long AmountPence { get; init; }

    public EntryKind Kind { get; init; }

    public long PostedAtMs { get; init; }

    public long? SettlementLineId { get; set; }
}

/// <summary>One bank instruction for one card on one settlement date.</summary>
public sealed class SettlementLine
{
    public long Id { get; init; }

    public DateOnly SettlementDate { get; init; }

    public required string CardToken { get; init; }

    public long AmountPence { get; init; }

    public int EntryCount { get; init; }

    public long CreatedAtMs { get; init; }
}

/// <summary>Records that a settlement date has been closed, so running it again does nothing.</summary>
public sealed class SettlementRun
{
    public DateOnly SettlementDate { get; init; }

    public int Lines { get; init; }

    public long CollectedPence { get; init; }

    public long RefundedPence { get; init; }

    public long CompletedAtMs { get; init; }
}
