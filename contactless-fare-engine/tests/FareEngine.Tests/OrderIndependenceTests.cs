using FareEngine.Domain;
using FareEngine.Simulator;

namespace FareEngine.Tests;

public class OrderIndependenceTests
{
    private static readonly DateOnly Monday = new(2026, 3, 23);

    [Fact]
    public void ArrivalOrder_NeverChangesAStatement()
    {
#pragma warning disable CA5394
        var random = new Random(7);
#pragma warning restore CA5394
        foreach (var card in Cards(40))
        {
            var ordered = Make.Engine.Rate("c", Monday, card, Make.Later);
            for (var i = 0; i < 5; i++)
            {
                var shuffled = card.ToArray();
                random.Shuffle(shuffled);
                var again = Make.Engine.Rate("c", Monday, shuffled, Make.Later);
                Assert.Equal(ordered.Journeys.Select(Key), again.Journeys.Select(Key));
            }
        }
    }

    [Fact]
    public void DeliveringATapTwice_ChangesNothing()
    {
        foreach (var card in Cards(20))
        {
            Assert.Equal(
                Make.Engine.Rate("c", Monday, card, Make.Later).Total,
                Make.Engine.Rate("c", Monday, [.. card, .. card], Make.Later).Total);
        }
    }

    [Fact]
    public void ChargesAreNeverNegativeAndNeverAboveTheSingleFare()
    {
        foreach (var journey in Cards(60).SelectMany(c => Make.Engine.Rate("c", Monday, c, Make.Later).Journeys))
        {
            Assert.InRange(journey.Charged.Pence, 0, journey.BaseFare.Pence);
        }
    }

    [Fact]
    public void WideningTheTapWindow_DoesNotChangeAWeek()
    {
        // The one-day margin either side must be enough: two more weeks of taps should make no difference.
        foreach (var card in Cards(40, weeks: 3))
        {
            var middle = Monday.AddDays(7);
            var (from, to) = RatingEngine.TapWindow(middle);
            var narrow = Make.Engine.Rate("c", middle, card.Where(t => t.OccurredAt >= from && t.OccurredAt < to), Make.Later);
            var wide = Make.Engine.Rate("c", middle, card, Make.Later);
            Assert.Equal(wide.Journeys.Select(Key), narrow.Journeys.Select(Key));
        }
    }

    private static (DateTimeOffset, JourneyStatus, Money, string) Key(PricedJourney j) =>
        (j.Journey.StartedAt, j.Journey.Status, j.Charged, string.Join(",", j.Journey.TapIds));

    private static IEnumerable<List<Tap>> Cards(int count, int weeks = 1) =>
        new TapGenerator(NorthmoorNetwork.Create(), seed: 11).Generate(count, Monday, weeks)
            .GroupBy(d => d.Tap.CardToken)
            .Select(g => g.Select(d => new Tap(d.Tap.Id, "c", d.Tap.PlaceId, d.Tap.Kind, d.Tap.OccurredAt)).ToList());
}
