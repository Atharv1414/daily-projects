using System.Text.Json;
using StockReservation.Application.Persistence;
using StockReservation.Domain;

namespace StockReservation.Application.Outbox;

/// <summary>Adds integration events to the current unit of work so they commit atomically with state.</summary>
public static class OutboxWriter
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public static void Enqueue<T>(StockDbContext db, string type, T payload, DateTimeOffset now) =>
        db.Outbox.Add(new OutboxMessage(type, JsonSerializer.Serialize(payload, Json), now));

    public static void EnqueueReservation(StockDbContext db, string type, Reservation r, DateTimeOffset now) =>
        Enqueue(
            db,
            type,
            new ReservationEvent(
                r.Id,
                r.OrderReference,
                r.WarehouseCode,
                r.Status.ToString(),
                [.. r.Lines.Select(l => new ReservationLineDto(l.Sku, l.Quantity))],
                now),
            now);

    public static void EnqueueStockLevel(StockDbContext db, string type, StockItem item, DateTimeOffset now) =>
        Enqueue(
            db,
            type,
            new StockLevelEvent(
                item.WarehouseCode,
                item.Sku,
                item.OnHand,
                item.Reserved,
                item.Available,
                item.ReorderPoint,
                now),
            now);
}
