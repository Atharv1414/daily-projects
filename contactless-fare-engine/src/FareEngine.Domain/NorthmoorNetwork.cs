namespace FareEngine.Domain;

/// <summary>An invented city network and its fares. Nothing here describes a real operator.</summary>
public static class NorthmoorNetwork
{
    public const string Rail = "Northmoor Rail";
    public const string Metro = "Northmoor Metro";
    public const string Buses = "Moorline Buses";

    public static Network Create() => new(
        [
            Station("QUAYSIDE", "Quayside", Metro, 1),
            Station("CORNMARKET", "Cornmarket", Metro, 1),
            Station("ASSEMBLY", "Assembly Rooms", Metro, 1),
            Station("VICTORIA", "Victoria Parade", Rail, 1),
            Station("FOUNDRY", "Foundry Lane", Metro, 1, 2),
            Station("INFIRMARY", "Royal Infirmary", Metro, 2),
            Station("COLLEGE", "College Green", Metro, 2),
            Station("DOCKS", "Albert Docks", Rail, 2),
            Station("HEATH", "Heath End", Metro, 2, 3),
            Station("ABBEY", "Abbey Wharf", Rail, 3),
            Station("MILLBROOK", "Millbrook", Rail, 3),
            Station("STANTON", "Stanton Park", Metro, 3),
            Station("RIDGEWAY", "Ridgeway", Rail, 4),
            Station("AIRPORT", "Northmoor Airport", Rail, 4),
            Station("COLLIERY", "Colliery Road", Metro, 4),
            Route("BUS-1", "Route 1"),
            Route("BUS-14", "Route 14"),
            Route("BUS-27", "Route 27"),
            Route("BUS-N3", "Night route N3"),
        ],
        [
            new Interchange("CORNMARKET", "VICTORIA", TimeSpan.FromMinutes(20)),
            new Interchange("DOCKS", "INFIRMARY", TimeSpan.FromMinutes(15)),
        ]);

    public static TariffBook Tariffs() => new(
        [
            new Tariff
            {
                Name = "2025",
                EffectiveFrom = new DateOnly(2025, 3, 2),
                PeakSingles = Pence(210, 290, 360, 430),
                OffPeakSingles = Pence(190, 220, 260, 310),
                CentralSupplement = new Money(70),
                BusSingle = new Money(175),
                MaximumFare = new Money(900),
                DailyBusCap = new Money(525),
                WeeklyBusCap = new Money(2470),
                DailyCaps = Pence(790, 890, 1050, 1280),
                WeeklyCaps = Pence(3990, 4470, 5280, 6440),
            },
            new Tariff
            {
                Name = "2026",
                EffectiveFrom = new DateOnly(2026, 3, 1),
                PeakSingles = Pence(220, 300, 380, 450),
                OffPeakSingles = Pence(200, 230, 270, 320),
                CentralSupplement = new Money(75),
                BusSingle = new Money(185),
                MaximumFare = new Money(950),
                DailyBusCap = new Money(555),
                WeeklyBusCap = new Money(2590),
                DailyCaps = Pence(830, 940, 1110, 1340),
                WeeklyCaps = Pence(4180, 4700, 5560, 6760),
            },
        ]);

    public static ServiceCalendar Calendar() => new(
        [
            new DateOnly(2026, 1, 1), new DateOnly(2026, 4, 3), new DateOnly(2026, 4, 6), new DateOnly(2026, 5, 4),
            new DateOnly(2026, 5, 25), new DateOnly(2026, 8, 31), new DateOnly(2026, 12, 25), new DateOnly(2026, 12, 28),
        ]);

    public static RatingEngine CreateEngine() => new(Create(), Tariffs(), Calendar());

    private static Place Station(string id, string name, string op, params int[] zones) =>
        new(id, name, TravelMode.Rail, op, zones);

    private static Place Route(string id, string name) => new(id, name, TravelMode.Bus, Buses, []);

    private static Money[] Pence(params int[] values) => [.. values.Select(v => new Money(v))];
}
