namespace StockReservation.Domain;

/// <summary>Events published to downstream systems (WMS, order management, purchasing).</summary>
public static class IntegrationEvents
{
    public const string ReservationCreated = "reservation.created";
    public const string ReservationConfirmed = "reservation.confirmed";
    public const string ReservationReleased = "reservation.released";
    public const string ReservationExpired = "reservation.expired";
    public const string StockLow = "stock.low";
    public const string StockReceived = "stock.received";
}

public sealed record ReservationEvent(
    Guid ReservationId,
    string OrderReference,
    string WarehouseCode,
    string Status,
    IReadOnlyList<ReservationLineDto> Lines,
    DateTimeOffset OccurredAt);

public sealed record ReservationLineDto(string Sku, int Quantity);

public sealed record StockLevelEvent(
    string WarehouseCode,
    string Sku,
    int OnHand,
    int Reserved,
    int Available,
    int ReorderPoint,
    DateTimeOffset OccurredAt);
