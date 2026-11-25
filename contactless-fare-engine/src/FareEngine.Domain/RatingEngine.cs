namespace FareEngine.Domain;

/// <summary>
/// Prices a card's week. Each journey is charged the amount it adds to the cheapest way of paying for
/// everything up to and including it. That makes a charge non-negative, makes charges add up exactly
/// to the capped total, and means an ordinary new tap never changes the price of an earlier day.
/// </summary>
public sealed class RatingEngine(Network network, TariffBook tariffs, ServiceCalendar calendar)
{
    /// <summary>How far either side of a week to read taps, so journeys crossing the boundary are whole.</summary>
    public static readonly TimeSpan Margin = TimeSpan.FromHours(24);

    private readonly JourneyBuilder _builder = new(network, tariffs);
    private readonly AutoCompleter _completer = new(tariffs);
    private readonly CapCalculator _caps = new(tariffs);

    public static (DateTimeOffset From, DateTimeOffset To) TapWindow(DateOnly weekStart) =>
        (ServiceCalendar.StartOf(weekStart) - Margin, ServiceCalendar.StartOf(weekStart.AddDays(7)) + Margin);

    public WeekStatement Rate(string cardToken, DateOnly weekStart, IEnumerable<Tap> taps, DateTimeOffset asOf)
    {
        if (ServiceCalendar.WeekStart(weekStart) != weekStart)
        {
            throw new ArgumentException("A week starts on a Monday.", nameof(weekStart));
        }

        var inWeek = _builder.Build(taps, asOf)
            .Where(j => j.ServiceDate >= weekStart && j.ServiceDate < weekStart.AddDays(7))
            .ToList();
        var journeys = _completer.Apply(inWeek, weekStart);
        var priced = new List<PricedJourney>(journeys.Count);
        var cappable = new List<CappableFare>(journeys.Count);
        var runningTotal = Money.Zero;
        foreach (var journey in journeys)
        {
            var (span, peak, fare) = BaseFare(journey);
            var charged = fare;
            if (!journey.IsIncomplete && fare > Money.Zero)
            {
                cappable.Add(new CappableFare(journey.ServiceDate, span?.Max, fare));
                var total = _caps.BestWeek(cappable, weekStart);
                charged = total - runningTotal;
                runningTotal = total;
            }

            priced.Add(new PricedJourney(journey, network.Get(journey.OriginId).Operator, span, peak, fare, charged));
        }

        return new WeekStatement(cardToken, weekStart, priced);
    }

    private (ZoneSpan? Span, bool Peak, Money Fare) BaseFare(Journey journey)
    {
        var tariff = tariffs.On(journey.ServiceDate);
        if (journey.Status is JourneyStatus.InProgress or JourneyStatus.SameStation || journey.HopperFree)
        {
            return (null, false, Money.Zero);
        }

        if (journey.IsIncomplete)
        {
            return (null, false, tariff.MaximumFare);
        }

        if (journey.Mode == TravelMode.Bus)
        {
            return (null, false, tariff.BusSingle);
        }

        var span = Network.Span(network.Get(journey.OriginId), network.Get(journey.DestinationId!));
        var peak = calendar.IsPeak(journey.StartedAt);
        return (span, peak, tariff.RailSingle(span, peak));
    }
}
