using FareEngine.Domain;

namespace FareEngine.Tests;

public class CappingTests
{
    private static readonly CapCalculator Caps = new(NorthmoorNetwork.Tariffs());

    private static CappableFare Fare(int day, int? zone, long pence) => new(Make.Monday.AddDays(day), zone, new Money(pence));

    [Fact]
    public void FourBuses_StopAtTheBusCap()
    {
        var taps = Enumerable.Range(0, 4).Select(i => Make.Bus(Make.On(0, $"{8 + (i * 2):00}:00"))).ToArray();
        Assert.Equal([185L, 185L, 185L, 0L], Make.Rate(taps).Journeys.Select(j => j.Charged.Pence));
    }

    [Fact]
    public void JourneyOutsideACap_IsAddedOnTop()
    {
        CappableFare[] fares = [Fare(0, 1, 300), Fare(0, 1, 300), Fare(0, 1, 300), Fare(0, 4, 320)];
        Assert.Equal(830 + 320, Caps.BestDay(fares, Make.Monday).Pence); // cheaper than the zone 4 cap
    }

    [Fact]
    public void WiderCap_WinsWhenItIsCheaper()
    {
        CappableFare[] fares = [Fare(0, 1, 300), Fare(0, 1, 300), Fare(0, 1, 300), Fare(0, 4, 525), Fare(0, 4, 525)];
        Assert.Equal(1340, Caps.BestDay(fares, Make.Monday).Pence);
    }

    [Fact]
    public void WeeklyCap_TakesOverLateInTheWeek()
    {
        var taps = Enumerable.Range(0, 7).SelectMany(d => new[]
        {
            Make.Trip("QUAYSIDE", "ASSEMBLY", d, "07:00", "07:20"), Make.Trip("ASSEMBLY", "QUAYSIDE", d, "12:00", "12:20"),
            Make.Trip("QUAYSIDE", "ASSEMBLY", d, "17:00", "17:20"),
        }.SelectMany(t => t)).ToArray();
        var statement = Make.Rate(taps);
        Assert.Equal(Make.Tariff.WeeklyCaps[0], statement.Total);
        Assert.Equal(Money.Zero, statement.DayTotals[Make.Monday.AddDays(6)]);
        Assert.Equal(830, statement.DayTotals[Make.Monday].Pence);
    }

    [Fact]
    public void IncompleteJourneys_StayOutsideTheCap()
    {
        var taps = Enumerable.Range(0, 4).Select(i => Make.Bus(Make.On(0, $"{8 + (i * 2):00}:00")))
            .Append(Make.In("ABBEY", Make.On(0, "20:00"))).ToArray();
        Assert.Equal(555 + 950, Make.Rate(taps).Total.Pence);
    }

    [Fact]
    public void TariffChangeMidWeek_PricesEachDayUnderItsOwnVersion()
    {
        // The 2026 fares start on Sunday 1 March, the last day of this week.
        var monday = new DateOnly(2026, 2, 23);
        Tap[] taps = [Make.Bus(Make.At("2026-02-28 12:00")), Make.Bus(Make.At("2026-03-01 12:00"))];
        var statement = Make.Engine.Rate(Make.Card, monday, taps, Make.Later);
        Assert.Equal([175L, 185L], statement.Journeys.Select(j => j.Charged.Pence));
    }

    [Fact]
    public void OperatorShares_AddUpToTheTotal()
    {
        var taps = Make.Trip("ABBEY", "QUAYSIDE", 0, "08:00", "08:40")
            .Concat(Make.Trip("QUAYSIDE", "ABBEY", 0, "17:00", "17:40"))
            .Concat([Make.Bus(Make.On(0, "20:00")), Make.Bus(Make.On(0, "22:00"))]).ToArray();
        var statement = Make.Rate(taps);
        Assert.Equal(1110, statement.Total.Pence);
        Assert.Equal(statement.Total, Money.Sum(statement.OperatorShares.Values));
    }

    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    public void RandomWeeks_NeverBreakTheCapRules(int seed)
    {
#pragma warning disable CA5394
        var random = new Random(seed);
        for (var round = 0; round < 150; round++)
        {
            var fares = new List<CappableFare>();
            var previous = Money.Zero;
            for (var i = 0; i < 25; i++)
            {
                var zone = random.Next(0, 5);
                var fare = Fare(random.Next(7), zone == 0 ? null : zone, random.Next(150, 600));
                fares.Add(fare);
                var total = Caps.BestWeek(fares, Make.Monday);
                Assert.True(total >= previous, "another journey must never make the week cheaper");
                Assert.True(total - previous <= fare.Fare, "and must never cost more than its own fare");
                Assert.True(total <= Make.Tariff.WeeklyCaps[^1], "or take the week past the widest cap");
                previous = total;
            }
        }
#pragma warning restore CA5394
    }
}
