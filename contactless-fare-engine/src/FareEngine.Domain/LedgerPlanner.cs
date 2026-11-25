namespace FareEngine.Domain;

public enum EntryKind
{
    Charge,
    Adjustment,
}

public sealed record PlannedEntry(DateOnly ServiceDate, Money Amount, EntryKind Kind);

/// <summary>
/// Works out what to append to the ledger so it matches a fresh statement. Entries are never edited:
/// if a late tap changes a day already posted, the difference is appended as an adjustment.
/// </summary>
public static class LedgerPlanner
{
    public static IReadOnlyList<PlannedEntry> Plan(
        WeekStatement statement,
        IReadOnlyDictionary<DateOnly, Money> posted,
        IReadOnlySet<DateOnly> settledDays)
    {
        ArgumentNullException.ThrowIfNull(statement);
        ArgumentNullException.ThrowIfNull(posted);
        ArgumentNullException.ThrowIfNull(settledDays);
        var wanted = statement.DayTotals;
        return
        [
            .. wanted.Keys.Union(posted.Keys)
                .Order()
                .Select(day => (Day: day, Delta: wanted.GetValueOrDefault(day) - posted.GetValueOrDefault(day)))
                .Where(x => x.Delta != Money.Zero)
                .Select(x => new PlannedEntry(
                    x.Day,
                    x.Delta,
                    x.Delta < Money.Zero || settledDays.Contains(x.Day) ? EntryKind.Adjustment : EntryKind.Charge)),
        ];
    }
}
