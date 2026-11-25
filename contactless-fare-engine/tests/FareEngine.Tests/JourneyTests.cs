using FareEngine.Domain;

namespace FareEngine.Tests;

public class JourneyTests
{
    private static JourneyStatus Only(params Tap[] taps) => Assert.Single(Make.Rate(taps).Journeys).Journey.Status;

    [Fact]
    public void EntryThenExit_IsOneJourney()
    {
        var journey = Assert.Single(Make.Rate(Make.Trip("ABBEY", "QUAYSIDE", 0, "08:00", "08:40")).Journeys);
        Assert.Equal(JourneyStatus.Complete, journey.Journey.Status);
        Assert.Equal(new ZoneSpan(1, 3), journey.Span);
        Assert.True(journey.Peak);
        Assert.Equal(new Money(380 + 75), journey.Charged);
    }

    [Fact]
    public void ForgottenExit_CostsTheMaximumFare()
    {
        var journey = Assert.Single(Make.Rate(Make.In("ABBEY", Make.On(0, "08:00"))).Journeys);
        Assert.Equal(JourneyStatus.MissingExit, journey.Journey.Status);
        Assert.Equal(Make.Tariff.MaximumFare, journey.Charged);
    }

    [Fact]
    public void ForgottenEntry_CostsTheMaximumFare() =>
        Assert.Equal(JourneyStatus.MissingEntry, Only(Make.Out("ABBEY", Make.On(0, "08:00"))));

    [Fact]
    public void JourneyStillUnderWay_IsNotChargedYet()
    {
        var start = Make.On(0, "08:00");
        var statement = Make.Engine.Rate(Make.Card, Make.Monday, [Make.In("ABBEY", start)], start.AddMinutes(30));
        Assert.Equal(JourneyStatus.InProgress, Assert.Single(statement.Journeys).Journey.Status);
        Assert.Equal(Money.Zero, statement.Total);
    }

    [Theory]
    [InlineData(150, 1)]
    [InlineData(151, 2)]
    public void JourneyBeyondTheTimeLimit_BecomesTwoIncompleteOnes(int minutes, int journeys)
    {
        var start = Make.On(0, "10:00");
        Assert.Equal(journeys, Make.Rate(Make.In("ABBEY", start), Make.Out("DOCKS", start.AddMinutes(minutes))).Journeys.Count);
    }

    [Theory]
    [InlineData(5, JourneyStatus.SameStation)]
    [InlineData(6, JourneyStatus.Complete)]
    public void LeavingTheSameStation_IsFreeWithinTheGracePeriod(int minutes, JourneyStatus status)
    {
        var start = Make.On(0, "10:00");
        Assert.Equal(status, Only(Make.In("ABBEY", start), Make.Out("ABBEY", start.AddMinutes(minutes))));
    }

    [Theory]
    [InlineData(59, 1)]
    [InlineData(60, 2)]
    public void SecondTapOnTheSameReader_IsIgnoredForAMinute(int seconds, int rides)
    {
        var start = Make.On(0, "10:00");
        Assert.Equal(rides, Make.Rate(Make.Bus(start), Make.Bus(start.AddSeconds(seconds))).Journeys.Count);
    }

    [Theory]
    [InlineData(20, 1)]
    [InlineData(21, 2)]
    public void WalkingBetweenLinkedStations_ContinuesTheJourney(int walk, int journeys)
    {
        var start = Make.On(0, "10:00");
        var change = start.AddMinutes(20 + walk);
        var statement = Make.Rate(
            Make.In("STANTON", start), Make.Out("CORNMARKET", start.AddMinutes(20)),
            Make.In("VICTORIA", change), Make.Out("MILLBROOK", change.AddMinutes(25)));
        Assert.Equal(journeys, statement.Journeys.Count);
    }

    [Fact]
    public void ContinuedJourney_KeepsItsOriginAndIsPricedEndToEnd()
    {
        var statement = Make.Rate(
            Make.In("STANTON", Make.On(0, "10:00")), Make.Out("CORNMARKET", Make.On(0, "10:20")),
            Make.In("VICTORIA", Make.On(0, "10:30")), Make.Out("MILLBROOK", Make.On(0, "11:00")));
        var journey = Assert.Single(statement.Journeys);
        Assert.Equal(("STANTON", "MILLBROOK", 1), (journey.Journey.OriginId, journey.Journey.DestinationId, journey.Journey.Interchanges));
        Assert.Equal(4, journey.Journey.TapIds.Count);
    }

    [Theory]
    [InlineData(62, 185)]
    [InlineData(63, 370)]
    public void SecondBus_IsFreeInsideTheHopperWindow(int minutes, long pence)
    {
        var start = Make.On(0, "10:00");
        Assert.Equal(pence, Make.Rate(Make.Bus(start), Make.Bus(start.AddMinutes(minutes), "BUS-14")).Total.Pence);
    }

    [Fact]
    public void HopperWindow_RunsFromThePaidRideNotTheFreeOne()
    {
        var start = Make.On(0, "10:00");
        var statement = Make.Rate(
            Make.Bus(start), Make.Bus(start.AddMinutes(50), "BUS-14"), Make.Bus(start.AddMinutes(100), "BUS-27"));
        Assert.Equal([185L, 0L, 185L], statement.Journeys.Select(j => j.Charged.Pence));
    }

    [Fact]
    public void BoardingABus_LeavesAnOpenRailJourneyIncomplete()
    {
        var statement = Make.Rate(Make.In("ABBEY", Make.On(0, "10:00")), Make.Bus(Make.On(0, "10:30")));
        Assert.Equal([JourneyStatus.MissingExit, JourneyStatus.Complete], statement.Journeys.Select(j => j.Journey.Status));
    }

    [Fact]
    public void JourneyAcrossTheWeekBoundary_BelongsToTheWeekItStarted()
    {
        Tap[] taps = [Make.In("ABBEY", Make.On(7, "04:10")), Make.Out("QUAYSIDE", Make.On(7, "04:50"))];
        Assert.Single(Make.Rate(taps).Journeys);
        Assert.Empty(Make.Engine.Rate(Make.Card, Make.Monday.AddDays(7), taps, Make.Later).Journeys);
    }

    [Fact]
    public void RegularCommuter_HasAForgottenExitFilledIn()
    {
        var taps = Enumerable.Range(0, 3).SelectMany(d => Make.Trip("ABBEY", "QUAYSIDE", d, "08:00", "08:40"))
            .Append(Make.In("ABBEY", Make.On(3, "08:00"))).ToArray();
        var last = Make.Rate(taps).Journeys[^1];
        Assert.Equal(JourneyStatus.AutoCompleted, last.Journey.Status);
        Assert.Equal("QUAYSIDE", last.Journey.DestinationId);
        Assert.Equal(new Money(455), last.BaseFare);
    }

    [Fact]
    public void ForgottenEntry_IsFilledInFromTheJourneyHome()
    {
        var taps = Enumerable.Range(0, 3).SelectMany(d => Make.Trip("QUAYSIDE", "ABBEY", d, "17:00", "17:40"))
            .Append(Make.Out("ABBEY", Make.On(3, "17:40"))).ToArray();
        var last = Make.Rate(taps).Journeys[^1].Journey;
        Assert.Equal(("QUAYSIDE", "ABBEY"), (last.OriginId, last.DestinationId));
    }

    [Fact]
    public void AutoCompletion_NeedsAClearPattern()
    {
        var taps = Enumerable.Range(0, 3).SelectMany(d => Make.Trip("ABBEY", "QUAYSIDE", d, "08:00", "08:40"))
            .Concat(Make.Trip("ABBEY", "DOCKS", 3, "08:00", "08:40"))
            .Append(Make.In("ABBEY", Make.On(4, "08:00"))).ToArray();
        Assert.Equal(JourneyStatus.MissingExit, Make.Rate(taps).Journeys[^1].Journey.Status);
    }

    [Fact]
    public void AutoCompletion_IsLimitedEachWeek()
    {
        var taps = Enumerable.Range(0, 3).SelectMany(d => Make.Trip("ABBEY", "QUAYSIDE", d, "08:00", "08:40"))
            .Concat(Enumerable.Range(3, 3).Select(d => Make.In("ABBEY", Make.On(d, "08:00")))).ToArray();
        var statuses = Make.Rate(taps).Journeys.Select(j => j.Journey.Status).ToList();
        Assert.Equal(2, statuses.Count(s => s == JourneyStatus.AutoCompleted));
        Assert.Equal(1, statuses.Count(s => s == JourneyStatus.MissingExit));
    }
}
