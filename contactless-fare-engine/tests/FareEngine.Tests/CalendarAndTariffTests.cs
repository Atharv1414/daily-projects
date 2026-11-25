using System.Globalization;
using FareEngine.Domain;

namespace FareEngine.Tests;

public class CalendarAndTariffTests
{
    [Theory]
    [InlineData("2026-11-03 04:29", "2026-11-02")]
    [InlineData("2026-11-03 04:30", "2026-11-03")]
    [InlineData("2026-07-01 03:29", "2026-06-30")] // 04:29 in summer time
    [InlineData("2026-07-01 03:30", "2026-07-01")]
    public void ServiceDay_StartsAtHalfPastFourLocalTime(string utc, string expected) =>
        Assert.Equal(expected, ServiceCalendar.ServiceDate(Make.At(utc)).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));

    [Theory]
    [InlineData("2026-03-28", 23)] // the service day that contains the skipped hour
    [InlineData("2026-10-24", 25)] // and the one that contains the repeated hour
    [InlineData("2026-11-02", 24)]
    public void ServiceDay_LengthFollowsTheClockChange(string day, int hours)
    {
        var date = DateOnly.Parse(day, CultureInfo.InvariantCulture);
        Assert.Equal(hours, (ServiceCalendar.StartOf(date.AddDays(1)) - ServiceCalendar.StartOf(date)).TotalHours);
    }

    [Theory]
    [InlineData("2026-11-02 06:29", false)]
    [InlineData("2026-11-02 06:30", true)]
    [InlineData("2026-11-02 09:30", false)]
    [InlineData("2026-11-02 18:59", true)]
    [InlineData("2026-11-02 19:00", false)]
    [InlineData("2026-11-07 08:00", false)] // Saturday
    [InlineData("2026-04-06 07:00", false)] // Easter Monday
    [InlineData("2026-07-01 05:30", true)] // 06:30 in summer time
    public void Peak_FollowsLocalTimeAndWorkingDays(string utc, bool peak) =>
        Assert.Equal(peak, NorthmoorNetwork.Calendar().IsPeak(Make.At(utc)));

    [Fact]
    public void WeekStart_IsMonday()
    {
        for (var i = 0; i < 7; i++)
        {
            Assert.Equal(Make.Monday, ServiceCalendar.WeekStart(Make.Monday.AddDays(i)));
        }
    }

    [Fact]
    public void TariffBook_PicksTheVersionInForce()
    {
        var book = NorthmoorNetwork.Tariffs();
        Assert.Equal("2025", book.On(new DateOnly(2026, 2, 28)).Name);
        Assert.Equal("2026", book.On(new DateOnly(2026, 3, 1)).Name);
        Assert.Throws<InvalidOperationException>(() => book.On(new DateOnly(2024, 1, 1)));
    }

    [Fact]
    public void TariffBook_RefusesCapsThatFallWithDistance()
    {
        var bad = Make.Tariff with { DailyCaps = [new(900), new(800), new(1000), new(1100)] };
        var error = Assert.Throws<InvalidTariffException>(() => new TariffBook([bad]));
        Assert.Contains("caps must not fall", error.Message);
    }

    [Fact]
    public void TariffBook_RefusesTwoVersionsOnOneDate() =>
        Assert.Throws<ArgumentException>(() => new TariffBook([Make.Tariff, Make.Tariff]));

    [Theory]
    [InlineData("FOUNDRY", "QUAYSIDE", 1, 1)] // a boundary station counts as zone 1 towards the centre
    [InlineData("FOUNDRY", "COLLEGE", 2, 2)] // and as zone 2 away from it
    [InlineData("FOUNDRY", "HEATH", 2, 2)]
    [InlineData("AIRPORT", "QUAYSIDE", 1, 4)]
    public void BoundaryStations_CountInTheRidersFavour(string from, string to, int min, int max)
    {
        var network = NorthmoorNetwork.Create();
        Assert.Equal(new ZoneSpan(min, max), Network.Span(network.Get(from), network.Get(to)));
    }

    [Theory]
    [InlineData(0, "£0.00")]
    [InlineData(5, "£0.05")]
    [InlineData(123456, "£1,234.56")]
    [InlineData(-250, "-£2.50")]
    public void Money_PrintsPoundsAndPence(long pence, string text) => Assert.Equal(text, new Money(pence).ToString());
}
