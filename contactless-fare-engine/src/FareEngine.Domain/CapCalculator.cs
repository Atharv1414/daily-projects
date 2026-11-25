namespace FareEngine.Domain;

/// <summary>One fare that can count towards a cap. A null zone means a bus, which every cap covers.</summary>
public readonly record struct CappableFare(DateOnly Date, int? MaxZone, Money Fare);

/// <summary>
/// The least a week can cost under the published caps. A cap for zones 1 to n covers every fare inside
/// those zones; fares outside it are added on top. The rider gets the best choice of cap for each day,
/// or the best weekly cap, whichever is cheaper.
/// </summary>
public sealed class CapCalculator(TariffBook tariffs)
{
    public Money BestWeek(IReadOnlyList<CappableFare> fares, DateOnly weekStart)
    {
        ArgumentNullException.ThrowIfNull(fares);
        var best = SumOfDays(fares, _ => true);
        var weekly = tariffs.On(weekStart);
        for (var zone = 0; zone <= weekly.ZoneCount; zone++)
        {
            var capZone = zone;
            var cap = capZone == 0 ? weekly.WeeklyBusCap : weekly.WeeklyCaps[capZone - 1];
            if (cap >= best)
            {
                continue; // the cap alone already costs more than the best found so far
            }

            best = Money.Min(best, cap + SumOfDays(fares, f => !Covered(f, capZone)));
        }

        return best;
    }

    public Money BestDay(IReadOnlyList<CappableFare> fares, DateOnly date)
    {
        ArgumentNullException.ThrowIfNull(fares);
        return BestDay(fares, date, _ => true);
    }

    private Money SumOfDays(IReadOnlyList<CappableFare> fares, Func<CappableFare, bool> include)
    {
        var total = Money.Zero;
        var seen = new HashSet<DateOnly>();
        foreach (var fare in fares)
        {
            if (seen.Add(fare.Date))
            {
                total += BestDay(fares, fare.Date, include);
            }
        }

        return total;
    }

    private Money BestDay(IReadOnlyList<CappableFare> fares, DateOnly date, Func<CappableFare, bool> include)
    {
        var tariff = tariffs.On(date);

        // bucket[0] holds buses, bucket[z] holds rail fares whose furthest zone is z.
        Span<long> bucket = stackalloc long[tariff.ZoneCount + 1];
        bucket.Clear();
        var sum = 0L;
        foreach (var fare in fares)
        {
            if (fare.Date == date && include(fare))
            {
                bucket[fare.MaxZone ?? 0] += fare.Fare.Pence;
                sum += fare.Fare.Pence;
            }
        }

        var best = sum;
        var covered = 0L;
        for (var zone = 0; zone <= tariff.ZoneCount; zone++)
        {
            covered += bucket[zone];
            var cap = zone == 0 ? tariff.DailyBusCap : tariff.DailyCaps[zone - 1];
            best = Math.Min(best, Math.Min(covered, cap.Pence) + (sum - covered));
        }

        return new Money(best);
    }

    private static bool Covered(CappableFare fare, int capZone) => fare.MaxZone is not { } zone || zone <= capZone;
}
