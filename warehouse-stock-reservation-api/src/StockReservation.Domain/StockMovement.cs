namespace StockReservation.Domain;

public enum MovementType
{
    Receipt,
    Reserve,
    Release,
    Expire,
    Allocate,
    Adjustment,
}

/// <summary>Append-only ledger entry: every change to a stock item is explained by a movement.</summary>
public sealed class StockMovement
{
    private StockMovement()
    {
        Sku = string.Empty;
        WarehouseCode = string.Empty;
        Actor = string.Empty;
    }

    public StockMovement(
        StockItem item,
        MovementType type,
        int quantity,
        string actor,
        DateTimeOffset occurredAt,
        Guid? reservationId = null,
        string? note = null)
    {
        Id = Guid.NewGuid();
        StockItemId = item.Id;
        Sku = item.Sku;
        WarehouseCode = item.WarehouseCode;
        Type = type;
        Quantity = quantity;
        OnHandAfter = item.OnHand;
        ReservedAfter = item.Reserved;
        Actor = actor;
        OccurredAt = occurredAt;
        ReservationId = reservationId;
        Note = note;
    }

    public Guid Id { get; private set; }

    public Guid StockItemId { get; private set; }

    public string Sku { get; private set; }

    public string WarehouseCode { get; private set; }

    public MovementType Type { get; private set; }

    /// <summary>Signed quantity: positive adds to the bucket the movement affects, negative removes.</summary>
    public int Quantity { get; private set; }

    public int OnHandAfter { get; private set; }

    public int ReservedAfter { get; private set; }

    public string Actor { get; private set; }

    public DateTimeOffset OccurredAt { get; private set; }

    public Guid? ReservationId { get; private set; }

    public string? Note { get; private set; }
}
