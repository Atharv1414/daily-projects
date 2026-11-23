using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using StockReservation.Application;
using StockReservation.Application.Common;
using StockReservation.Application.Inventory;
using StockReservation.Application.Persistence;
using StockReservation.Application.Reservations;
using StockReservation.Domain;

namespace StockReservation.Tests;

public sealed class ReservationServiceTests : IDisposable
{
    private readonly TestDb _t = new();

    public ReservationServiceTests()
    {
        _t.SeedItem("MAN1", "KIT-1", onHand: 10, reorderPoint: 3);
        _t.SeedItem("MAN1", "TOY-2", onHand: 5);
    }

    public void Dispose() => _t.Dispose();

    private async Task<Result<CreateReservationOutcome>> CreateAsync(CreateReservationCommand cmd)
    {
        using var db = _t.NewContext();
        return await _t.Reservations(db).CreateAsync(cmd, "planner", CancellationToken.None);
    }

    [Fact]
    public async Task Create_HoldsStockWritesLedgerAndOutbox()
    {
        var result = await CreateAsync(Commands.Reserve("key-000001", ("KIT-1", 4), ("toy-2", 1)));

        Assert.True(result.IsSuccess);
        Assert.False(result.Value!.Replayed);
        Assert.Equal(4, _t.Item("MAN1", "KIT-1").Reserved);
        Assert.Equal(1, _t.Item("MAN1", "TOY-2").Reserved);
        using var db = _t.NewContext();
        Assert.Equal(2, await db.Movements.CountAsync(m => m.Type == MovementType.Reserve));
        Assert.Equal(1, await db.Outbox.CountAsync(m => m.Type == IntegrationEvents.ReservationCreated));
        Assert.Equal(TestDb.Start.AddMinutes(30), result.Value.Reservation.ExpiresAt);
    }

    [Fact]
    public async Task Create_IsAllOrNothingWhenOneLineIsShort()
    {
        var result = await CreateAsync(Commands.Reserve("key-000002", ("KIT-1", 4), ("TOY-2", 6)));

        Assert.Equal(ErrorKind.InsufficientStock, result.Error!.Kind);
        Assert.Contains("TOY-2", result.Error.Message, StringComparison.Ordinal);
        Assert.Equal(0, _t.Item("MAN1", "KIT-1").Reserved);
        using var db = _t.NewContext();
        Assert.Equal(0, await db.Reservations.CountAsync());
        Assert.Equal(0, await db.Outbox.CountAsync());
    }

    [Fact]
    public async Task Create_UnknownSku_IsNotFound()
    {
        var result = await CreateAsync(Commands.Reserve("key-000003", ("NOPE-1", 1)));
        Assert.Equal("stock.unknown_sku", result.Error!.Code);
    }

    [Fact]
    public async Task Create_SameKeySameBody_ReplaysWithoutReservingTwice()
    {
        var first = await CreateAsync(Commands.Reserve("key-000004", ("KIT-1", 2)));
        var second = await CreateAsync(Commands.Reserve("key-000004", ("KIT-1", 2)));

        Assert.True(second.Value!.Replayed);
        Assert.Equal(first.Value!.Reservation.Id, second.Value.Reservation.Id);
        Assert.Equal(2, _t.Item("MAN1", "KIT-1").Reserved);
    }

    [Fact]
    public async Task Create_SameKeyDifferentBody_IsConflict()
    {
        await CreateAsync(Commands.Reserve("key-000005", ("KIT-1", 2)));
        var reused = await CreateAsync(Commands.Reserve("key-000005", ("KIT-1", 3)));
        Assert.Equal("idempotency.key_reused", reused.Error!.Code);
    }

    [Fact]
    public async Task Create_CrossingReorderPoint_EmitsStockLowOnce()
    {
        await CreateAsync(Commands.Reserve("key-000006", ("KIT-1", 7))); // available 3 == reorder point
        await CreateAsync(Commands.Reserve("key-000007", ("KIT-1", 1))); // already below: no second event
        using var db = _t.NewContext();
        Assert.Equal(1, await db.Outbox.CountAsync(m => m.Type == IntegrationEvents.StockLow));
    }

    [Fact]
    public async Task Confirm_AllocatesStock()
    {
        var created = await CreateAsync(Commands.Reserve("key-000008", ("KIT-1", 4)));
        using var db = _t.NewContext();
        var confirmed = await _t.Reservations(db).ConfirmAsync(created.Value!.Reservation.Id, "picker", CancellationToken.None);

        Assert.Equal(ReservationStatus.Confirmed, confirmed.Value!.Status);
        var item = _t.Item("MAN1", "KIT-1");
        Assert.Equal((6, 0), (item.OnHand, item.Reserved));
    }

    [Fact]
    public async Task Release_ReturnsStockAndSecondReleaseIsRejected()
    {
        var created = await CreateAsync(Commands.Reserve("key-000009", ("KIT-1", 4)));
        var id = created.Value!.Reservation.Id;
        using var db = _t.NewContext();
        var service = _t.Reservations(db);

        Assert.True((await service.ReleaseAsync(id, "planner", CancellationToken.None)).IsSuccess);
        Assert.Equal("reservation.invalid_transition", (await service.ReleaseAsync(id, "planner", CancellationToken.None)).Error!.Code);
        Assert.Equal(0, _t.Item("MAN1", "KIT-1").Reserved);
    }

    [Fact]
    public async Task ExpireDue_ReleasesOnlyOverdueHolds()
    {
        await CreateAsync(Commands.Reserve("key-000010", ("KIT-1", 2)) with { HoldMinutes = 10 });
        await CreateAsync(Commands.Reserve("key-000011", ("KIT-1", 3)) with { HoldMinutes = 60 });
        _t.Clock.Advance(TimeSpan.FromMinutes(15));

        using var db = _t.NewContext();
        var expired = await _t.Reservations(db).ExpireDueAsync(100, CancellationToken.None);

        Assert.Equal(1, expired);
        Assert.Equal(3, _t.Item("MAN1", "KIT-1").Reserved);
        Assert.Equal(1, await db.Reservations.CountAsync(r => r.Status == ReservationStatus.Expired));
    }

    [Fact]
    public async Task Confirm_UnknownReservation_IsNotFound()
    {
        using var db = _t.NewContext();
        var result = await _t.Reservations(db).ConfirmAsync(Guid.NewGuid(), "picker", CancellationToken.None);
        Assert.Equal(ErrorKind.NotFound, result.Error!.Kind);
    }

    [Fact]
    public async Task StaleWrite_IsDetectedByVersionToken()
    {
        using var a = _t.NewContext();
        using var b = _t.NewContext();
        var itemA = await a.StockItems.SingleAsync(s => s.Sku == "KIT-1");
        var itemB = await b.StockItems.SingleAsync(s => s.Sku == "KIT-1");
        itemA.Reserve(6, TestDb.Start);
        itemB.Reserve(6, TestDb.Start);
        await a.SaveChangesAsync();

        // Without the concurrency token this second write would oversell (12 reserved of 10).
        await Assert.ThrowsAsync<DbUpdateConcurrencyException>(() => b.SaveChangesAsync());
        Assert.Equal(6, _t.Item("MAN1", "KIT-1").Reserved);
    }

    [Fact]
    public async Task List_FiltersByStatusAndPages()
    {
        for (var i = 0; i < 5; i++)
        {
            await CreateAsync(Commands.Reserve($"key-list-{i:D3}", ("KIT-1", 1)));
        }

        using var db = _t.NewContext();
        var page = await _t.Reservations(db).ListAsync(ReservationStatus.Pending, "man1", PageRequest.Create(2, 2), CancellationToken.None);
        Assert.Equal(5, page.TotalCount);
        Assert.Equal(3, page.TotalPages);
        Assert.Equal(2, page.Items.Count);
        Assert.True(page.HasNext);
    }
}

public sealed class InventoryAndOutboxTests : IDisposable
{
    private readonly TestDb _t = new();

    public InventoryAndOutboxTests()
    {
        _t.SeedItem("MAN1", "KIT-1", 100, reorderPoint: 10, costPence: 2_500);
        _t.SeedItem("MAN1", "KIT-2", 5, reorderPoint: 10, costPence: 1_000);
        _t.SeedItem("BRS1", "TOY_9", 20, reorderPoint: 1, costPence: 499);
    }

    public void Dispose() => _t.Dispose();

    [Theory]
    [InlineData(null, null, false, 3)]
    [InlineData("man1", null, false, 2)]
    [InlineData(null, "kit", false, 2)]
    [InlineData(null, null, true, 1)]
    [InlineData(null, "TOY_", false, 1)]
    [InlineData(null, "TOYX", false, 0)]
    public async Task Search_AppliesFilters(string? warehouse, string? prefix, bool below, int expected)
    {
        using var db = _t.NewContext();
        var page = await _t.Inventory(db).SearchAsync(new StockQuery(warehouse, prefix, below, PageRequest.Create(1, 50)), CancellationToken.None);
        Assert.Equal(expected, page.TotalCount);
    }

    [Fact]
    public async Task Valuation_AggregatesInPounds()
    {
        using var db = _t.NewContext();
        var rows = await _t.Inventory(db).ValuationAsync(CancellationToken.None);
        var man = rows.Single(r => r.WarehouseCode == "MAN1");
        Assert.Equal(2_550m, man.StockValueGbp); // 100 x £25 + 5 x £10
        Assert.Equal(1, man.SkusBelowReorder);
    }

    [Fact]
    public async Task Receive_AddsStockAndLedgerEntry()
    {
        using var db = _t.NewContext();
        var result = await _t.Inventory(db).ReceiveAsync("MAN1", "KIT-2", 50, "PO-7781", "planner", CancellationToken.None);
        Assert.Equal(55, result.Value!.OnHand);
        var movements = await _t.Inventory(db).MovementsAsync("MAN1", "KIT-2", PageRequest.Create(1, 10), CancellationToken.None);
        Assert.Equal("PO-7781", movements!.Items.Single().Note);
    }

    [Fact]
    public async Task Adjust_RequiresReason()
    {
        using var db = _t.NewContext();
        var result = await _t.Inventory(db).AdjustAsync("MAN1", "KIT-1", -5, " ", "admin", CancellationToken.None);
        Assert.Equal("adjustment.reason_required", result.Error!.Code);
    }

    [Fact]
    public async Task Dispatcher_PublishesThenBacksOffAndDeadLetters()
    {
        using (var db = _t.NewContext())
        {
            await _t.Inventory(db).ReceiveAsync("MAN1", "KIT-1", 1, null, "planner", CancellationToken.None);
            await _t.Reservations(db).CreateAsync(Commands.Reserve("key-outbox-1", ("KIT-1", 1)), "planner", CancellationToken.None);
        }

        _t.Publisher.FailingTypes[IntegrationEvents.ReservationCreated] = true;
        using var ctx = _t.NewContext();
        var dispatcher = _t.Dispatcher(ctx);

        var first = await dispatcher.DispatchBatchAsync(CancellationToken.None);
        Assert.Equal((1, 1, 0), (first.Published, first.Failed, first.DeadLettered));

        // Not yet due for retry: nothing happens.
        Assert.Equal(0, (await dispatcher.DispatchBatchAsync(CancellationToken.None)).Failed);

        _t.Clock.Advance(TimeSpan.FromSeconds(10));
        await dispatcher.DispatchBatchAsync(CancellationToken.None);
        _t.Clock.Advance(TimeSpan.FromSeconds(20));
        var last = await dispatcher.DispatchBatchAsync(CancellationToken.None);
        Assert.Equal(1, last.DeadLettered);

        var stats = await dispatcher.GetStatsAsync(CancellationToken.None);
        Assert.Equal((0, 1, 1), (stats.Pending, stats.Published, stats.DeadLettered));
    }

    [Fact]
    public async Task Reconcile_IsCleanAfterMixedOperations()
    {
        using var db = _t.NewContext();
        var reservations = _t.Reservations(db);
        var a = await reservations.CreateAsync(Commands.Reserve("key-recon-1", ("KIT-1", 5)), "p", CancellationToken.None);
        await reservations.CreateAsync(Commands.Reserve("key-recon-2", ("KIT-1", 7)), "p", CancellationToken.None);
        await reservations.ConfirmAsync(a.Value!.Reservation.Id, "picker", CancellationToken.None);

        Assert.Empty(await _t.Inventory(db).ReconcileAsync(CancellationToken.None));
    }
}

public sealed class ConcurrencyTests
{
    [Fact]
    public async Task ParallelReservations_OnOneSku_NeverOversell()
    {
        var path = Path.Combine(Path.GetTempPath(), $"stock-test-{Guid.NewGuid():N}.db");
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Workers:Enabled"] = "false",
                ["Reservations:MaxConcurrencyRetries"] = "20",
            })
            .Build();
        var services = new ServiceCollection()
            .AddLogging()
            .AddStockReservation(config, $"Data Source={path};Default Timeout=30")
            .BuildServiceProvider();
        try
        {
            await using (var scope = services.CreateAsyncScope())
            {
                var db = scope.ServiceProvider.GetRequiredService<StockDbContext>();
                await db.Database.MigrateAsync();
                await db.Database.ExecuteSqlRawAsync("PRAGMA journal_mode=WAL;");
                db.StockItems.Add(new StockItem("MAN1", "HOT-1", "Hot", 50, 0, 100, DateTimeOffset.UtcNow));
                await db.SaveChangesAsync();
            }

            var successes = 0;
            await Parallel.ForEachAsync(Enumerable.Range(0, 120), new ParallelOptions { MaxDegreeOfParallelism = 16 }, async (i, ct) =>
            {
                await using var scope = services.CreateAsyncScope();
                var service = scope.ServiceProvider.GetRequiredService<ReservationService>();
                var result = await service.CreateAsync(Commands.Reserve($"key-par-{i:D4}", ("HOT-1", 1)), "load", ct);
                if (result.IsSuccess)
                {
                    Interlocked.Increment(ref successes);
                }
            });

            await using var check = services.CreateAsyncScope();
            var item = await check.ServiceProvider.GetRequiredService<StockDbContext>().StockItems.SingleAsync();
            Assert.Equal(50, successes);
            Assert.Equal(50, item.Reserved);
        }
        finally
        {
            await services.DisposeAsync();
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            foreach (var suffix in new[] { "", "-wal", "-shm" })
            {
                File.Delete(path + suffix);
            }
        }
    }
}
