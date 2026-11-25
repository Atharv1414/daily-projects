using System.Diagnostics;
using FareEngine.Application;
using FareEngine.Application.Persistence;
using FareEngine.Application.Rating;
using FareEngine.Application.Settlement;
using FareEngine.Application.Taps;
using FareEngine.Domain;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace FareEngine.Simulator;

public sealed record SimulationReport(
    int Deliveries, int StoredTaps, int Duplicates, int LedgerEntries, int Adjustments, int SettledDays,
    Money Gross, Money Charged, Money Collected, Money Refunded, int CardWeeks, int MismatchedCardWeeks,
    int CardDaysOverCap, int AutoCompleted, int Incomplete, TimeSpan IngestTime, TimeSpan RatingTime, int WeeksRated);

/// <summary>
/// Plays deliveries through the real database in arrival order, rating and settling each day as it closes,
/// then checks the ledger against a clean rating of every tap in its true order.
/// </summary>
public static class Simulation
{
    public static async Task<SimulationReport> RunAsync(int cards, int weeks, int seed, CancellationToken ct = default)
    {
        var monday = new DateOnly(2026, 3, 23); // includes the spring clock change, the Easter weekend and two bank holidays
        var path = Path.Combine(Path.GetTempPath(), $"fares-{Guid.NewGuid():N}.db");
        var clock = new SimulatedClock(ServiceCalendar.StartOf(monday));
        var services = new ServiceCollection();
        services.AddSingleton<TimeProvider>(clock);
        services.AddSingleton<IConfiguration>(new ConfigurationBuilder().Build());
        services.AddLogging(l => l.SetMinimumLevel(LogLevel.Warning).AddConsole());
        services.AddFareEngine($"Data Source={path}");
        try
        {
            await using var provider = services.BuildServiceProvider();
            return await PlayAsync(provider, clock, cards, weeks, seed, monday, ct);
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            foreach (var suffix in new[] { "", "-wal", "-shm" })
            {
                File.Delete(path + suffix);
            }
        }
    }

    private static async Task<SimulationReport> PlayAsync(
        ServiceProvider provider, SimulatedClock clock, int cards, int weeks, int seed, DateOnly monday, CancellationToken ct)
    {
        await using (var scope = provider.CreateAsyncScope())
        {
            await scope.ServiceProvider.GetRequiredService<FareDbContext>().Database.MigrateAsync(ct);
        }

        var network = provider.GetRequiredService<Network>();
        var processor = provider.GetRequiredService<RatingProcessor>();
        var deliveries = new TapGenerator(network, seed).Generate(cards, monday, weeks);
        var ingest = new Stopwatch();
        var rating = new Stopwatch();
        var (duplicates, weeksRated, settledDays) = (0, 0, 0);
        var (collected, refunded) = (Money.Zero, Money.Zero);
        var lastDay = monday.AddDays((weeks * 7) + 4); // long enough for the latest taps to arrive
        var byClose = deliveries.OrderBy(d => d.ArrivesAt).ThenBy(d => d.Tap.Id)
            .GroupBy(d => ServiceCalendar.ServiceDate(d.ArrivesAt.AddHours(-3)))
            .ToDictionary(g => g.Key, g => g.ToList());
        // Days close three hours into the next one, so the first close belongs to the Sunday before.
        for (var day = monday.AddDays(-1); day <= lastDay; day = day.AddDays(1))
        {
            clock.Set(ServiceCalendar.StartOf(day.AddDays(1)).AddHours(3));
            ingest.Start();
            foreach (var batch in byClose.GetValueOrDefault(day, []).Chunk(250))
            {
                await using var scope = provider.CreateAsyncScope();
                var results = await scope.ServiceProvider.GetRequiredService<TapIngestion>()
                    .IngestAsync([.. batch.Select(b => b.Tap)], "simulator", ct: ct);
                duplicates += results.Count(r => r.Outcome == TapOutcome.Duplicate);
            }

            ingest.Stop();
            rating.Start();
            weeksRated += (await processor.DrainAsync(ct)).Rated;
            rating.Stop();
            await using var settle = provider.CreateAsyncScope();
            var summary = await settle.ServiceProvider.GetRequiredService<SettlementService>().SettleAsync(day, ct);
            collected += summary.Collected;
            refunded += summary.Refunded;
            settledDays++;
        }

        return await CheckAsync(
            provider, deliveries, clock.GetUtcNow(), duplicates, weeksRated, settledDays, collected, refunded,
            ingest.Elapsed, rating.Elapsed, ct);
    }

    private static async Task<SimulationReport> CheckAsync(
        ServiceProvider provider, IReadOnlyList<Delivery> deliveries, DateTimeOffset now, int duplicates, int weeksRated,
        int settledDays, Money collected, Money refunded, TimeSpan ingestTime, TimeSpan ratingTime, CancellationToken ct)
    {
        await using var scope = provider.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<FareDbContext>();
        var engine = provider.GetRequiredService<RatingEngine>();
        var tariffs = provider.GetRequiredService<TariffBook>();
        var ledger = (await db.Ledger.AsNoTracking().ToListAsync(ct))
            .GroupBy(e => (e.CardToken, e.WeekStart))
            .ToDictionary(g => g.Key, g => g.Sum(e => e.AmountPence));
        var (gross, charged) = (Money.Zero, Money.Zero);
        var (cardWeeks, mismatched, overCap, completed, incomplete) = (0, 0, 0, 0, 0);
        var seenWeeks = new HashSet<(string, DateOnly)>();
        foreach (var card in deliveries.GroupBy(d => d.Tap.CardToken))
        {
            var taps = card.Select(d => new Tap(d.Tap.Id, d.Tap.CardToken, d.Tap.PlaceId, d.Tap.Kind, d.Tap.OccurredAt)).ToList();
            foreach (var week in taps.Select(t => ServiceCalendar.WeekStart(ServiceCalendar.ServiceDate(t.OccurredAt))).Distinct())
            {
                seenWeeks.Add((card.Key, week));
                var (from, to) = RatingEngine.TapWindow(week);
                var statement = engine.Rate(card.Key, week, taps.Where(t => t.OccurredAt >= from && t.OccurredAt < to), now);
                cardWeeks++;
                gross += statement.Gross;
                charged += statement.Total;
                mismatched += ledger.GetValueOrDefault((card.Key, week)) == statement.Total.Pence ? 0 : 1;
                completed += statement.Journeys.Count(j => j.Journey.Status == JourneyStatus.AutoCompleted);
                incomplete += statement.Journeys.Count(j => j.Journey.IsIncomplete);
                overCap += statement.Journeys.Where(j => !j.Journey.IsIncomplete)
                    .GroupBy(j => j.Journey.ServiceDate)
                    .Count(g => Money.Sum(g.Select(j => j.Charged)) > tariffs.On(g.Key).DailyCaps[^1]);
            }
        }

        mismatched += ledger.Count(l => !seenWeeks.Contains(l.Key) && l.Value != 0);
        return new SimulationReport(
            deliveries.Count, await db.Taps.CountAsync(ct), duplicates, await db.Ledger.CountAsync(ct),
            await db.Ledger.CountAsync(e => e.Kind == EntryKind.Adjustment, ct), settledDays, gross, charged, collected, refunded,
            cardWeeks, mismatched, overCap, completed, incomplete, ingestTime, ratingTime, weeksRated);
    }
}
