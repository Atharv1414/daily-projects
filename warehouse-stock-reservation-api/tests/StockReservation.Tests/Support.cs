using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using StockReservation.Application.Common;
using StockReservation.Application.Inventory;
using StockReservation.Application.Outbox;
using StockReservation.Application.Persistence;
using StockReservation.Application.Reservations;
using StockReservation.Domain;

namespace StockReservation.Tests;

/// <summary>A clock tests can move forward.</summary>
public sealed class TestClock(DateTimeOffset start) : TimeProvider
{
    private DateTimeOffset _now = start;

    public override DateTimeOffset GetUtcNow() => _now;

    public void Advance(TimeSpan by) => _now += by;
}

/// <summary>An in-memory SQLite database with the real migrations applied, plus service factories.</summary>
public sealed class TestDb : IDisposable
{
    public static readonly DateTimeOffset Start = new(2026, 11, 23, 9, 0, 0, TimeSpan.Zero);

    private readonly SqliteConnection _connection;

    public TestDb()
    {
        _connection = new SqliteConnection("Data Source=:memory:");
        _connection.Open();
        using var db = NewContext();
        db.Database.Migrate();
    }

    public TestClock Clock { get; } = new(Start);

    public InMemoryEventPublisher Publisher { get; } = new();

    public ReservationOptions ReservationOptions { get; } = new();

    public WorkerOptions WorkerOptions { get; } = new() { OutboxMaxAttempts = 3, OutboxBaseRetrySeconds = 10 };

    public StockDbContext NewContext() =>
        new(new DbContextOptionsBuilder<StockDbContext>().UseSqlite(_connection).Options);

    public ReservationService Reservations(StockDbContext db) =>
        new(db, Clock, Options.Create(ReservationOptions), NullLogger<ReservationService>.Instance);

    public InventoryService Inventory(StockDbContext db) => new(db, Clock, Options.Create(ReservationOptions));

    public OutboxDispatcher Dispatcher(StockDbContext db) =>
        new(db, Publisher, Clock, Options.Create(WorkerOptions), NullLogger<OutboxDispatcher>.Instance);

    public void SeedItem(string warehouse, string sku, int onHand, int reorderPoint = 0, long costPence = 1000)
    {
        using var db = NewContext();
        db.StockItems.Add(new StockItem(warehouse, sku, "Test " + sku, onHand, reorderPoint, costPence, Start));
        db.SaveChanges();
    }

    public StockItem Item(string warehouse, string sku)
    {
        using var db = NewContext();
        return db.StockItems.AsNoTracking().Single(s => s.WarehouseCode == warehouse && s.Sku == sku);
    }

    public void Dispose() => _connection.Dispose();
}

public static class Commands
{
    public static CreateReservationCommand Reserve(string key, params (string Sku, int Qty)[] lines) =>
        new("ORD-" + key, "MAN1", [.. lines.Select(l => new ReservationLineRequest(l.Sku, l.Qty))], key);
}
