namespace FareEngine.Domain;

public enum TravelMode
{
    Rail,
    Bus,
}

/// <summary>A rail station or a bus route: anywhere a card can be tapped. Boundary stations belong to two zones.</summary>
public sealed record Place(string Id, string Name, TravelMode Mode, string Operator, IReadOnlyList<int> Zones);

/// <summary>Two stations close enough to walk between as part of one journey.</summary>
public sealed record Interchange(string FromId, string ToId, TimeSpan Limit);

/// <summary>The zones a journey uses, after boundary stations are resolved in the rider's favour.</summary>
public readonly record struct ZoneSpan(int Min, int Max)
{
    public bool CoveredByCap(int capMaxZone) => Max <= capMaxZone;

    public override string ToString() => Min == Max ? $"zone {Min}" : $"zones {Min}-{Max}";
}

public sealed class Network
{
    private readonly Dictionary<string, Place> _places;
    private readonly Dictionary<(string From, string To), TimeSpan> _interchanges;

    public Network(IEnumerable<Place> places, IEnumerable<Interchange> interchanges)
    {
        ArgumentNullException.ThrowIfNull(places);
        ArgumentNullException.ThrowIfNull(interchanges);
        _places = places.ToDictionary(p => p.Id, StringComparer.Ordinal);
        _interchanges = [];
        foreach (var link in interchanges)
        {
            _ = Get(link.FromId);
            _ = Get(link.ToId);
            _interchanges[(link.FromId, link.ToId)] = link.Limit;
            _interchanges[(link.ToId, link.FromId)] = link.Limit;
        }
    }

    public IReadOnlyCollection<Place> Places => _places.Values;

    public bool TryGet(string id, out Place? place) => _places.TryGetValue(id, out place);

    public Place Get(string id) =>
        _places.TryGetValue(id, out var place) ? place : throw new UnknownPlaceException(id);

    /// <summary>How long a rider may take to walk between two stations, or null if they are not linked.</summary>
    public TimeSpan? InterchangeLimit(string fromId, string toId) =>
        _interchanges.TryGetValue((fromId, toId), out var limit) ? limit : null;

    /// <summary>Picks the cheapest reading of boundary stations: the pair of zones that are closest together.</summary>
    public static ZoneSpan Span(Place origin, Place destination)
    {
        ArgumentNullException.ThrowIfNull(origin);
        ArgumentNullException.ThrowIfNull(destination);
        var best = origin.Zones
            .SelectMany(a => destination.Zones.Select(b => new ZoneSpan(Math.Min(a, b), Math.Max(a, b))))
            .OrderBy(s => s.Max - s.Min)
            .ThenBy(s => s.Max);
        return best.First();
    }
}

public sealed class UnknownPlaceException(string placeId) : Exception($"Unknown station or route '{placeId}'.")
{
    public string PlaceId { get; } = placeId;
}
