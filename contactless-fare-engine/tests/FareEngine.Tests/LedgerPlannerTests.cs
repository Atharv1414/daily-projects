using FareEngine.Domain;

namespace FareEngine.Tests;

public class LedgerPlannerTests
{
    private static readonly IReadOnlySet<DateOnly> NothingSettled = new HashSet<DateOnly>();

    private static WeekStatement OneBus() => Make.Rate(Make.Bus(Make.On(0, "10:00")));

    [Fact]
    public void NewDay_IsACharge()
    {
        var entry = Assert.Single(LedgerPlanner.Plan(OneBus(), new Dictionary<DateOnly, Money>(), NothingSettled));
        Assert.Equal(new PlannedEntry(Make.Monday, new Money(185), EntryKind.Charge), entry);
    }

    [Fact]
    public void NothingChanged_PostsNothing() =>
        Assert.Empty(LedgerPlanner.Plan(OneBus(), new Dictionary<DateOnly, Money> { [Make.Monday] = new(185) }, NothingSettled));

    [Fact]
    public void LowerPrice_PostsTheDifferenceBack()
    {
        var entry = Assert.Single(LedgerPlanner.Plan(OneBus(), new Dictionary<DateOnly, Money> { [Make.Monday] = new(950) }, NothingSettled));
        Assert.Equal((-765, EntryKind.Adjustment), (entry.Amount.Pence, entry.Kind));
    }

    [Fact]
    public void HigherPriceAfterSettlement_IsAnAdjustment()
    {
        var entry = Assert.Single(LedgerPlanner.Plan(
            OneBus(), new Dictionary<DateOnly, Money> { [Make.Monday] = new(100) }, new HashSet<DateOnly> { Make.Monday }));
        Assert.Equal((85, EntryKind.Adjustment), (entry.Amount.Pence, entry.Kind));
    }

    [Fact]
    public void DayThatNoLongerHasJourneys_IsReversedInFull()
    {
        var tuesday = Make.Monday.AddDays(1);
        var plan = LedgerPlanner.Plan(
            OneBus(), new Dictionary<DateOnly, Money> { [Make.Monday] = new(185), [tuesday] = new(300) }, NothingSettled);
        Assert.Equal(new PlannedEntry(tuesday, new Money(-300), EntryKind.Adjustment), Assert.Single(plan));
    }
}
