namespace FareEngine.Domain;

/// <summary>
/// Turns instants into service days. A service day starts at 04:30 local time, so a 01:00 journey
/// home belongs to the evening before. Taps are stored in UTC and converted here, which keeps
/// both clock changes correct.
/// </summary>
public sealed class ServiceCalendar
{
    public static readonly TimeSpan DayStart = new(4, 30, 0);

    private static readonly TimeZoneInfo London = TimeZoneInfo.FindSystemTimeZoneById("Europe/London");
    private readonly HashSet<DateOnly> _bankHolidays;

    public ServiceCalendar(IEnumerable<DateOnly>? bankHolidays = null) => _bankHolidays = [.. bankHolidays ?? []];

    public static DateTime Local(DateTimeOffset instant) =>
        TimeZoneInfo.ConvertTime(instant, London).DateTime;

    public static DateOnly ServiceDate(DateTimeOffset instant) =>
        DateOnly.FromDateTime(Local(instant) - DayStart);

    public static DateOnly WeekStart(DateOnly date) => date.AddDays(-(((int)date.DayOfWeek + 6) % 7));

    /// <summary>The instant a service day begins. 04:30 is never skipped or repeated by a clock change.</summary>
    public static DateTimeOffset StartOf(DateOnly serviceDate)
    {
        var local = serviceDate.ToDateTime(TimeOnly.FromTimeSpan(DayStart));
        return new DateTimeOffset(local, London.GetUtcOffset(local)).ToUniversalTime();
    }

    /// <summary>Peak fares apply by the clock time at the start of the journey, on working weekdays.</summary>
    public bool IsPeak(DateTimeOffset instant)
    {
        var local = Local(instant);
        var date = DateOnly.FromDateTime(local);
        if (local.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday || _bankHolidays.Contains(date))
        {
            return false;
        }

        var time = local.TimeOfDay;
        return (time >= new TimeSpan(6, 30, 0) && time < new TimeSpan(9, 30, 0))
            || (time >= new TimeSpan(16, 0, 0) && time < new TimeSpan(19, 0, 0));
    }
}
