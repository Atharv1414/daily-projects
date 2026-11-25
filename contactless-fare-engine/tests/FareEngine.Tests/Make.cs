using System.Globalization;
using FareEngine.Domain;

namespace FareEngine.Tests;

/// <summary>Short builders. Times are UTC; the default week is in winter, when London is on UTC.</summary>
internal static class Make
{
    public const string Card = "card-1";
    public static readonly DateOnly Monday = new(2026, 11, 2);
    public static readonly RatingEngine Engine = NorthmoorNetwork.CreateEngine();
    public static readonly Tariff Tariff = NorthmoorNetwork.Tariffs().On(Monday);
    public static readonly DateTimeOffset Later = At("2026-12-01 12:00");

    public static DateTimeOffset At(string utc) =>
        DateTimeOffset.Parse(utc, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal);

    public static DateTimeOffset On(int day, string time) => At($"{Monday.AddDays(day):yyyy-MM-dd} {time}");

    public static Tap In(string place, DateTimeOffset at) => new(Guid.NewGuid(), Card, place, TapKind.Entry, at);

    public static Tap Out(string place, DateTimeOffset at) => new(Guid.NewGuid(), Card, place, TapKind.Exit, at);

    public static Tap Bus(DateTimeOffset at, string route = "BUS-1") => new(Guid.NewGuid(), Card, route, TapKind.Board, at);

    public static Tap[] Trip(string from, string to, int day, string leave, string arrive) =>
        [In(from, On(day, leave)), Out(to, On(day, arrive))];

    public static WeekStatement Rate(params Tap[] taps) => Engine.Rate(Card, Monday, taps, Later);
}
