using FareEngine.Application.Taps;
using FareEngine.Domain;

namespace FareEngine.Api.Endpoints;

public sealed record TapBatch(IReadOnlyList<IncomingTap> Taps);

public sealed record TapBatchResult(int Accepted, int Duplicates, int Conflicts, int Rejected, IReadOnlyList<TapResult> Results);

public sealed record CorrectionRequest(Guid Id, string PlaceId, TapKind Kind, DateTimeOffset OccurredAt, string Reason);

public sealed record JourneyView(
    DateOnly ServiceDate,
    DateTimeOffset StartedAt,
    DateTimeOffset? EndedAt,
    TravelMode Mode,
    JourneyStatus Status,
    string From,
    string? To,
    string? Zones,
    bool Peak,
    long FarePence,
    long ChargedPence,
    string? Note);

public sealed record StatementView(
    string CardToken,
    DateOnly WeekStart,
    long GrossPence,
    long SavedPence,
    long TotalPence,
    IReadOnlyDictionary<DateOnly, long> DayTotals,
    IReadOnlyDictionary<string, long> OperatorShares,
    IReadOnlyList<JourneyView> Journeys)
{
    public static StatementView From(WeekStatement s, Network network)
    {
        ArgumentNullException.ThrowIfNull(s);
        ArgumentNullException.ThrowIfNull(network);
        return new StatementView(
            s.CardToken,
            s.WeekStart,
            s.Gross.Pence,
            s.Saved.Pence,
            s.Total.Pence,
            s.DayTotals.OrderBy(d => d.Key).ToDictionary(d => d.Key, d => d.Value.Pence),
            s.OperatorShares.ToDictionary(o => o.Key, o => o.Value.Pence, StringComparer.Ordinal),
            [
                .. s.Journeys.Select(p => new JourneyView(
                    p.Journey.ServiceDate,
                    p.Journey.StartedAt,
                    p.Journey.EndedAt,
                    p.Journey.Mode,
                    p.Journey.Status,
                    network.Get(p.Journey.OriginId).Name,
                    p.Journey.DestinationId is { } to ? network.Get(to).Name : null,
                    p.Span?.ToString(),
                    p.Peak,
                    p.BaseFare.Pence,
                    p.Charged.Pence,
                    p.Journey.Note)),
            ]);
    }
}

public sealed record LedgerView(long Id, DateOnly ServiceDate, long AmountPence, EntryKind Kind, DateTimeOffset PostedAt, bool Settled);

public sealed record LedgerPage(IReadOnlyList<LedgerView> Entries, long? NextAfter);

public sealed record SettlementView(DateOnly Date, bool AlreadyDone, int Lines, long CollectedPence, long RefundedPence);
