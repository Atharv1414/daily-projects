namespace FareEngine.Domain;

/// <summary>One dated version of the fares. Old versions are kept so past weeks can be re-rated exactly.</summary>
public sealed record Tariff
{
    public required string Name { get; init; }

    public required DateOnly EffectiveFrom { get; init; }

    /// <summary>Rail single fares by number of zones crossed (index 0 is one zone).</summary>
    public required IReadOnlyList<Money> PeakSingles { get; init; }

    public required IReadOnlyList<Money> OffPeakSingles { get; init; }

    /// <summary>Extra for any journey that touches zone 1.</summary>
    public required Money CentralSupplement { get; init; }

    public required Money BusSingle { get; init; }

    public required Money MaximumFare { get; init; }

    public required Money DailyBusCap { get; init; }

    public required Money WeeklyBusCap { get; init; }

    /// <summary>Daily caps for zones 1 to n (index 0 is zone 1 only). Each also covers all buses.</summary>
    public required IReadOnlyList<Money> DailyCaps { get; init; }

    public required IReadOnlyList<Money> WeeklyCaps { get; init; }

    public TimeSpan HopperWindow { get; init; } = TimeSpan.FromMinutes(62);

    public TimeSpan MaximumJourney { get; init; } = TimeSpan.FromMinutes(150);

    public TimeSpan SameStationGrace { get; init; } = TimeSpan.FromMinutes(5);

    public TimeSpan PassbackWindow { get; init; } = TimeSpan.FromSeconds(60);

    public int AutoCompletionsPerWeek { get; init; } = 2;

    public int AutoCompletionEvidence { get; init; } = 3;

    public int ZoneCount => DailyCaps.Count;

    public Money RailSingle(ZoneSpan span, bool peak)
    {
        var table = peak ? PeakSingles : OffPeakSingles;
        var fare = table[span.Max - span.Min];
        return span.Min == 1 ? fare + CentralSupplement : fare;
    }

    /// <summary>Refuses tariffs that would make a wider cap cheaper than a narrower one.</summary>
    public void Validate()
    {
        var problems = new List<string>();
        Require(DailyCaps.Count > 0 && DailyCaps.Count == WeeklyCaps.Count, "daily and weekly caps must cover the same zones");
        Require(PeakSingles.Count == DailyCaps.Count && OffPeakSingles.Count == DailyCaps.Count, "single fares must cover every zone count");
        Require(Ascending(DailyCaps) && Ascending(WeeklyCaps), "caps must not fall as zones are added");
        Require(Ascending(PeakSingles) && Ascending(OffPeakSingles), "fares must not fall with distance");
        Require(DailyBusCap <= DailyCaps[0] && WeeklyBusCap <= WeeklyCaps[0], "bus caps must not exceed the zone 1 caps");
        Require(PeakSingles.Zip(OffPeakSingles).All(p => p.First >= p.Second), "off-peak must not cost more than peak");
        Require(HopperWindow > TimeSpan.Zero && MaximumJourney > TimeSpan.Zero, "time limits must be positive");
        if (problems.Count > 0)
        {
            throw new InvalidTariffException(Name, problems);
        }

        void Require(bool ok, string message)
        {
            if (!ok)
            {
                problems.Add(message);
            }
        }

        static bool Ascending(IReadOnlyList<Money> values) =>
            values.Zip(values.Skip(1)).All(p => p.First <= p.Second);
    }
}

public sealed class InvalidTariffException(string name, IReadOnlyList<string> problems)
    : Exception($"Tariff '{name}' is not valid: {string.Join("; ", problems)}.")
{
    public IReadOnlyList<string> Problems { get; } = problems;
}

/// <summary>Finds the tariff in force on a service date.</summary>
public sealed class TariffBook
{
    private readonly Tariff[] _versions;

    public TariffBook(IEnumerable<Tariff> versions)
    {
        _versions = [.. versions.OrderBy(v => v.EffectiveFrom)];
        if (_versions.Length == 0)
        {
            throw new ArgumentException("At least one tariff is needed.", nameof(versions));
        }

        foreach (var version in _versions)
        {
            version.Validate();
        }

        if (_versions.DistinctBy(v => v.EffectiveFrom).Count() != _versions.Length)
        {
            throw new ArgumentException("Two tariffs start on the same date.", nameof(versions));
        }
    }

    public Tariff On(DateOnly date) =>
        _versions.LastOrDefault(v => v.EffectiveFrom <= date)
        ?? throw new InvalidOperationException($"No tariff is in force on {date:yyyy-MM-dd}.");
}
