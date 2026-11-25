using FareEngine.Application.Taps;
using FareEngine.Domain;

namespace FareEngine.Simulator;

/// <summary>What readers deliver: the tap and the moment it reaches the server.</summary>
public sealed record Delivery(IncomingTap Tap, DateTimeOffset ArrivesAt);

/// <summary>Seeded riders with habits: commuters, bus users and occasional travellers, with real-world mistakes.</summary>
public sealed class TapGenerator(Network network, int seed)
{
    private static readonly string[] Central = ["QUAYSIDE", "CORNMARKET", "ASSEMBLY", "VICTORIA"];
    private static readonly string[] Outer = ["INFIRMARY", "COLLEGE", "DOCKS", "HEATH", "ABBEY", "MILLBROOK", "STANTON", "RIDGEWAY", "AIRPORT", "COLLIERY"];
    private readonly string[] _routes = [.. network.Places.Where(p => p.Mode == TravelMode.Bus).Select(p => p.Id).Order(StringComparer.Ordinal)];

#pragma warning disable CA5394 // seeded on purpose: the simulation has to be repeatable
    private readonly Random _random = new(seed);

    public IReadOnlyList<Delivery> Generate(int cards, DateOnly monday, int weeks)
    {
        var deliveries = new List<Delivery>();
        for (var card = 0; card < cards; card++)
        {
            var token = $"card-{card:00000}";
            var kind = _random.NextDouble();
            var home = Pick(Outer);
            var work = Pick(Central);
            var route = Pick(_routes);
            for (var day = 0; day < weeks * 7; day++)
            {
                var date = monday.AddDays(day);
                var weekend = date.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday;
                if (kind < 0.5)
                {
                    Commuter(deliveries, token, date, weekend, home, work, route);
                }
                else if (kind < 0.8)
                {
                    BusRider(deliveries, token, date, weekend);
                }
                else if (_random.NextDouble() < 0.3)
                {
                    Trip(deliveries, token, date, Minutes(10, 14), Pick(Outer), Pick(Central));
                    Trip(deliveries, token, date, Minutes(17, 23), Pick(Central), Pick(Outer));
                }
            }
        }

        return deliveries;
    }

    private void Commuter(List<Delivery> into, string token, DateOnly date, bool weekend, string home, string work, string route)
    {
        if (_random.NextDouble() < (weekend ? 0.75 : 0.12))
        {
            return;
        }

        Trip(into, token, date, Minutes(7, 9), home, weekend ? Pick(Central) : work);
        if (_random.NextDouble() < 0.35)
        {
            Bus(into, token, date, Minutes(12, 14), route);
        }

        Trip(into, token, date, Minutes(16, 20), weekend ? Pick(Central) : work, home);
        if (_random.NextDouble() < 0.06)
        {
            Trip(into, token, date, Minutes(23, 25), Pick(Central), home); // a late one, after midnight
        }
    }

    private void BusRider(List<Delivery> into, string token, DateOnly date, bool weekend)
    {
        var rides = weekend ? _random.Next(0, 3) : _random.Next(1, 6);
        var minute = Minutes(6, 10);
        for (var i = 0; i < rides; i++)
        {
            Bus(into, token, date, minute, Pick(_routes));
            minute += _random.Next(15, 240);
        }
    }

    private void Trip(List<Delivery> into, string token, DateOnly date, int minute, string from, string to)
    {
        var missed = _random.NextDouble();
        if (missed >= 0.012)
        {
            Add(into, token, date, minute, from, TapKind.Entry);
        }

        if (missed is < 0.012 or >= 0.030)
        {
            Add(into, token, date, minute + _random.Next(12, 70), to, TapKind.Exit);
        }
    }

    private void Bus(List<Delivery> into, string token, DateOnly date, int minute, string route) =>
        Add(into, token, date, minute, route, TapKind.Board);

    private void Add(List<Delivery> into, string token, DateOnly date, int minute, string place, TapKind kind)
    {
        // Minutes count from 04:30, so a service day never spills into the next one by accident.
        var at = ServiceCalendar.StartOf(date).AddMinutes(minute - 270).AddSeconds(_random.Next(60));
        var tap = new IncomingTap(NextGuid(), token, place, kind, at);
        var delivery = new Delivery(tap, at + Lateness());
        into.Add(delivery);
        if (_random.NextDouble() < 0.03)
        {
            into.Add(delivery with { ArrivesAt = delivery.ArrivesAt.AddMinutes(_random.Next(1, 90)) }); // a retry
        }

        if (_random.NextDouble() < 0.01)
        {
            into.Add(new Delivery(tap with { Id = NextGuid(), OccurredAt = at.AddSeconds(4) }, delivery.ArrivesAt)); // a double tap
        }
    }

    /// <summary>Most taps arrive in seconds; a bus in a garage with no signal may take days.</summary>
    private TimeSpan Lateness() => _random.NextDouble() switch
    {
        < 0.90 => TimeSpan.FromSeconds(_random.Next(1, 30)),
        < 0.98 => TimeSpan.FromMinutes(_random.Next(5, 240)),
        _ => TimeSpan.FromHours(_random.Next(12, 72)),
    };

    private int Minutes(int fromHour, int toHour) => _random.Next(fromHour * 60, toHour * 60);

    private Guid NextGuid()
    {
        Span<byte> bytes = stackalloc byte[16];
        _random.NextBytes(bytes);
        return new Guid(bytes);
    }

    private string Pick(string[] options) => options[_random.Next(options.Length)];
#pragma warning restore CA5394
}
