namespace FareEngine.Domain;

public enum JourneyStatus
{
    Complete,
    InProgress,
    MissingExit,
    MissingEntry,
    TooLong,
    SameStation,
    AutoCompleted,
}

/// <summary>A journey rebuilt from taps. It carries the taps it used, so a charge can be explained.</summary>
public sealed record Journey
{
    public required TravelMode Mode { get; init; }

    public required JourneyStatus Status { get; init; }

    public required string OriginId { get; init; }

    public string? DestinationId { get; init; }

    public required DateTimeOffset StartedAt { get; init; }

    public DateTimeOffset? EndedAt { get; init; }

    public required IReadOnlyList<Guid> TapIds { get; init; }

    public bool HopperFree { get; init; }

    public int Interchanges { get; init; }

    public string? Note { get; init; }

    public DateOnly ServiceDate => ServiceCalendar.ServiceDate(StartedAt);

    /// <summary>Incomplete journeys cost the maximum fare and sit outside every cap.</summary>
    public bool IsIncomplete => Status is JourneyStatus.MissingEntry or JourneyStatus.MissingExit or JourneyStatus.TooLong;
}

public sealed record PricedJourney(Journey Journey, string Operator, ZoneSpan? Span, bool Peak, Money BaseFare, Money Charged)
{
    public Money Saved => BaseFare - Charged;
}

/// <summary>What one card owes for one Monday to Sunday week.</summary>
public sealed record WeekStatement(string CardToken, DateOnly WeekStart, IReadOnlyList<PricedJourney> Journeys)
{
    public Money Gross => Money.Sum(Journeys.Select(j => j.BaseFare));

    public Money Total => Money.Sum(Journeys.Select(j => j.Charged));

    public Money Saved => Gross - Total;

    public IReadOnlyDictionary<DateOnly, Money> DayTotals => Journeys
        .GroupBy(j => j.Journey.ServiceDate)
        .ToDictionary(g => g.Key, g => Money.Sum(g.Select(j => j.Charged)));

    public IReadOnlyDictionary<string, Money> OperatorShares => Journeys
        .GroupBy(j => j.Operator, StringComparer.Ordinal)
        .ToDictionary(g => g.Key, g => Money.Sum(g.Select(j => j.Charged)), StringComparer.Ordinal);
}
