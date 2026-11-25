namespace FareEngine.Domain;

public enum TapKind
{
    Entry,
    Exit,
    Board,
}

public enum TapSource
{
    Reader,
    StaffCorrection,
}

/// <summary>One presentation of a card. Identity comes from the reader, so retries are recognisable.</summary>
public sealed record Tap(
    Guid Id,
    string CardToken,
    string PlaceId,
    TapKind Kind,
    DateTimeOffset OccurredAt,
    TapSource Source = TapSource.Reader)
{
    /// <summary>A total order that does not depend on when the tap reached us.</summary>
    public static readonly IComparer<Tap> Chronological = Comparer<Tap>.Create((a, b) =>
    {
        var byTime = a.OccurredAt.CompareTo(b.OccurredAt);
        return byTime != 0 ? byTime : a.Id.CompareTo(b.Id);
    });
}
