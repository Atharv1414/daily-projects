using System.Collections.Concurrent;
using System.Diagnostics;
using System.Globalization;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using StockReservation.Application;
using StockReservation.Application.Inventory;
using StockReservation.Application.Persistence;
using StockReservation.Application.Reservations;
using StockReservation.Domain;

namespace StockReservation.LoadTest;

/// <summary>
/// Hammers a handful of "hot" SKUs with concurrent reservations against a real SQLite file (WAL mode)
/// and proves the invariants hold: no oversell, ledger reconciles, idempotent replays are exact.
/// Usage: dotnet run -c Release --project src/StockReservation.LoadTest -- [requests] [parallelism] [stockPerSku]
/// </summary>
internal static class Program
{
    private const string Warehouse = "DIR1";
    private static readonly string[] HotSkus = ["KIT-00001", "KIT-00002", "TOY-00003", "ELC-00004", "PET-00005"];

    private static async Task<int> Main(string[] args)
    {
        var requests = ParseArg(args, 0, 3000);
        var parallelism = ParseArg(args, 1, 32);
        var stockPerSku = ParseArg(args, 2, 1500);
        var dbPath = Path.Combine(Path.GetTempPath(), $"stock-loadtest-{Guid.NewGuid():N}.db");

        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Workers:Enabled"] = "false",
                ["Reservations:MaxConcurrencyRetries"] = "20",
            })
            .Build();
        var services = new ServiceCollection()
            .AddLogging(b => b.AddSimpleConsole().SetMinimumLevel(LogLevel.Warning))
            .AddStockReservation(config, $"Data Source={dbPath};Default Timeout=60")
            .BuildServiceProvider();

        try
        {
            await SetUpAsync(services, stockPerSku);
            var report = await RunReservationsAsync(services, requests, parallelism);
            var replay = await RunReplayAsync(services, report.SuccessfulKeys.Take(200).ToList(), parallelism);
            return await VerifyAndPrintAsync(services, report, replay, requests, parallelism, stockPerSku);
        }
        finally
        {
            await services.DisposeAsync();
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            foreach (var suffix in new[] { "", "-wal", "-shm" })
            {
                File.Delete(dbPath + suffix);
            }
        }
    }

    private static int ParseArg(string[] args, int index, int fallback) =>
        args.Length > index && int.TryParse(args[index], NumberStyles.Integer, CultureInfo.InvariantCulture, out var v) ? v : fallback;

    private static async Task SetUpAsync(IServiceProvider services, int stockPerSku)
    {
        await using var scope = services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<StockDbContext>();
        await db.Database.MigrateAsync();
        await db.Database.ExecuteSqlRawAsync("PRAGMA journal_mode=WAL;");
        var now = DateTimeOffset.UtcNow;
        foreach (var sku in HotSkus)
        {
            db.StockItems.Add(new StockItem(Warehouse, sku, "Hot line " + sku, stockPerSku, 50, 1999, now));
        }

        await db.SaveChangesAsync();
    }

    private sealed record RunReport(
        int Succeeded,
        int Insufficient,
        int Conflicts,
        long TotalRetries,
        double ElapsedSeconds,
        double[] LatenciesMs,
        ConcurrentDictionary<string, int> ReservedBySku,
        ConcurrentBag<(string Key, Guid Id)> SuccessfulKeys);

    private static async Task<RunReport> RunReservationsAsync(IServiceProvider services, int requests, int parallelism)
    {
        var latencies = new double[requests];
        var reservedBySku = new ConcurrentDictionary<string, int>(StringComparer.Ordinal);
        var keys = new ConcurrentBag<(string, Guid)>();
        int ok = 0, insufficient = 0, conflicts = 0;
        long retries = 0;

        var total = Stopwatch.StartNew();
        await Parallel.ForEachAsync(
            Enumerable.Range(0, requests),
            new ParallelOptions { MaxDegreeOfParallelism = parallelism },
            async (i, ct) =>
            {
                var random = new Random(i);
                var sku = HotSkus[random.Next(HotSkus.Length)];
                var qty = random.Next(1, 4);
                var key = $"load-{i:D6}-key";
                var command = new CreateReservationCommand($"ORD-{i:D6}", Warehouse, [new ReservationLineRequest(sku, qty)], key);

                await using var scope = services.CreateAsyncScope();
                var service = scope.ServiceProvider.GetRequiredService<ReservationService>();
                var sw = Stopwatch.StartNew();
                var result = await service.CreateAsync(command, "loadtest", ct);
                latencies[i] = sw.Elapsed.TotalMilliseconds;

                if (result.IsSuccess)
                {
                    Interlocked.Increment(ref ok);
                    Interlocked.Add(ref retries, result.Value!.ConcurrencyRetries);
                    reservedBySku.AddOrUpdate(sku, qty, (_, v) => v + qty);
                    keys.Add((key, result.Value.Reservation.Id));
                }
                else if (result.Error!.Kind == ErrorKind.InsufficientStock)
                {
                    Interlocked.Increment(ref insufficient);
                }
                else
                {
                    Interlocked.Increment(ref conflicts);
                }
            });
        total.Stop();
        return new RunReport(ok, insufficient, conflicts, retries, total.Elapsed.TotalSeconds, latencies, reservedBySku, keys);
    }

    private static async Task<(int Matched, int Total)> RunReplayAsync(
        IServiceProvider services,
        List<(string Key, Guid Id)> keys,
        int parallelism)
    {
        var matched = 0;
        await Parallel.ForEachAsync(
            keys,
            new ParallelOptions { MaxDegreeOfParallelism = parallelism },
            async (entry, ct) =>
            {
                await using var scope = services.CreateAsyncScope();
                var service = scope.ServiceProvider.GetRequiredService<ReservationService>();
                var db = scope.ServiceProvider.GetRequiredService<StockDbContext>();
                var original = await db.Reservations.AsNoTracking().Include(r => r.Lines).FirstAsync(r => r.Id == entry.Id, ct);
                var line = original.Lines[0];
                var result = await service.CreateAsync(
                    new CreateReservationCommand(original.OrderReference, original.WarehouseCode, [new ReservationLineRequest(line.Sku, line.Quantity)], entry.Key),
                    "loadtest",
                    ct);
                if (result is { IsSuccess: true, Value.Replayed: true } && result.Value.Reservation.Id == entry.Id)
                {
                    Interlocked.Increment(ref matched);
                }
            });
        return (matched, keys.Count);
    }

    private static async Task<int> VerifyAndPrintAsync(
        IServiceProvider services,
        RunReport report,
        (int Matched, int Total) replay,
        int requests,
        int parallelism,
        int stockPerSku)
    {
        await using var scope = services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<StockDbContext>();
        var inventory = scope.ServiceProvider.GetRequiredService<InventoryService>();
        var items = await db.StockItems.AsNoTracking().OrderBy(s => s.Sku).ToListAsync();
        var mismatches = await inventory.ReconcileAsync(CancellationToken.None);

        var sorted = report.LatenciesMs.Order().ToArray();
        double Percentile(double p) => sorted[Math.Clamp((int)Math.Ceiling(p * sorted.Length) - 1, 0, sorted.Length - 1)];
        var inv = CultureInfo.InvariantCulture;

        Console.WriteLine(string.Create(inv, $"Concurrent reservation load test: {requests} requests, parallelism {parallelism}, {HotSkus.Length} hot SKUs x {stockPerSku} units"));
        Console.WriteLine(string.Create(inv, $"  succeeded            {report.Succeeded,8}"));
        Console.WriteLine(string.Create(inv, $"  insufficient stock   {report.Insufficient,8}"));
        Console.WriteLine(string.Create(inv, $"  gave up (conflicts)  {report.Conflicts,8}"));
        Console.WriteLine(string.Create(inv, $"  optimistic retries   {report.TotalRetries,8}  ({report.TotalRetries / (double)Math.Max(1, report.Succeeded):F2} per success)"));
        Console.WriteLine(string.Create(inv, $"  throughput           {requests / report.ElapsedSeconds,8:F0} req/s  ({report.ElapsedSeconds:F2}s)"));
        Console.WriteLine(string.Create(inv, $"  latency p50/p95/p99  {Percentile(0.50):F1} / {Percentile(0.95):F1} / {Percentile(0.99):F1} ms"));
        Console.WriteLine();
        Console.WriteLine("  SKU         on-hand  reserved  expected  oversold?");
        var failures = 0;
        foreach (var item in items)
        {
            var expected = report.ReservedBySku.GetValueOrDefault(item.Sku);
            var bad = item.Reserved != expected || item.Reserved > item.OnHand;
            failures += bad ? 1 : 0;
            Console.WriteLine(string.Create(inv, $"  {item.Sku,-10} {item.OnHand,8} {item.Reserved,9} {expected,9}  {(bad ? "YES" : "no")}"));
        }

        Console.WriteLine();
        Console.WriteLine(string.Create(inv, $"  idempotent replays returning the original reservation: {replay.Matched}/{replay.Total}"));
        Console.WriteLine(string.Create(inv, $"  ledger reconciliation mismatches: {mismatches.Count}"));
        var passed = failures == 0 && mismatches.Count == 0 && replay.Matched == replay.Total;
        Console.WriteLine(passed ? "RESULT: PASS (no oversell, ledger consistent)" : "RESULT: FAIL");
        return passed ? 0 : 1;
    }
}
