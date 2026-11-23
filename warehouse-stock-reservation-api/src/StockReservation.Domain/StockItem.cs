namespace StockReservation.Domain;

/// <summary>
/// Stock of one SKU at one warehouse. Invariant: <c>0 &lt;= Reserved &lt;= OnHand</c>.
/// <see cref="Version"/> is an optimistic-concurrency token bumped on every mutation.
/// </summary>
public sealed class StockItem
{
    private StockItem()
    {
        Sku = string.Empty;
        WarehouseCode = string.Empty;
        Description = string.Empty;
    }

    public StockItem(
        string warehouseCode,
        string sku,
        string description,
        int onHand,
        int reorderPoint,
        long unitCostPence,
        DateTimeOffset now)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(warehouseCode);
        ArgumentException.ThrowIfNullOrWhiteSpace(sku);
        ArgumentOutOfRangeException.ThrowIfNegative(onHand);
        ArgumentOutOfRangeException.ThrowIfNegative(reorderPoint);
        ArgumentOutOfRangeException.ThrowIfNegative(unitCostPence);

        Id = Guid.NewGuid();
        WarehouseCode = warehouseCode;
        Sku = sku;
        Description = description;
        OnHand = onHand;
        ReorderPoint = reorderPoint;
        UnitCostPence = unitCostPence;
        UpdatedAt = now;
    }

    public Guid Id { get; private set; }

    public string WarehouseCode { get; private set; }

    public string Sku { get; private set; }

    public string Description { get; private set; }

    public int OnHand { get; private set; }

    public int Reserved { get; private set; }

    public int Available => OnHand - Reserved;

    public int ReorderPoint { get; private set; }

    public long UnitCostPence { get; private set; }

    public int Version { get; private set; }

    public DateTimeOffset UpdatedAt { get; private set; }

    public bool IsBelowReorderPoint => Available <= ReorderPoint;

    /// <summary>Holds <paramref name="quantity"/> units for a pending reservation.</summary>
    public Result Reserve(int quantity, DateTimeOffset now)
    {
        if (quantity <= 0)
        {
            return DomainError.Validation("quantity.not_positive", "Quantity must be positive.");
        }

        if (quantity > Available)
        {
            return DomainError.Insufficient(
                "stock.insufficient",
                $"{Sku} at {WarehouseCode}: requested {quantity}, available {Available}.");
        }

        Reserved += quantity;
        Touch(now);
        return Result.Success();
    }

    /// <summary>Returns held units to the available pool (cancel or expiry).</summary>
    public Result Release(int quantity, DateTimeOffset now)
    {
        if (quantity <= 0 || quantity > Reserved)
        {
            return DomainError.InvalidState(
                "stock.release_exceeds_reserved",
                $"Cannot release {quantity} of {Sku}; only {Reserved} reserved.");
        }

        Reserved -= quantity;
        Touch(now);
        return Result.Success();
    }

    /// <summary>Converts held units into a pick: they leave both the reserved and on-hand counts.</summary>
    public Result Allocate(int quantity, DateTimeOffset now)
    {
        if (quantity <= 0 || quantity > Reserved)
        {
            return DomainError.InvalidState(
                "stock.allocate_exceeds_reserved",
                $"Cannot allocate {quantity} of {Sku}; only {Reserved} reserved.");
        }

        Reserved -= quantity;
        OnHand -= quantity;
        Touch(now);
        return Result.Success();
    }

    /// <summary>Goods-in: adds received units to on-hand stock.</summary>
    public Result Receive(int quantity, DateTimeOffset now)
    {
        if (quantity <= 0)
        {
            return DomainError.Validation("quantity.not_positive", "Received quantity must be positive.");
        }

        if ((long)OnHand + quantity > int.MaxValue)
        {
            return DomainError.Validation("quantity.overflow", "Receipt would overflow on-hand stock.");
        }

        OnHand += quantity;
        Touch(now);
        return Result.Success();
    }

    /// <summary>Stock-count correction. Cannot push on-hand below what is already promised.</summary>
    public Result Adjust(int delta, DateTimeOffset now)
    {
        if (delta == 0)
        {
            return DomainError.Validation("adjustment.zero", "Adjustment delta must be non-zero.");
        }

        var newOnHand = (long)OnHand + delta;
        if (newOnHand < Reserved)
        {
            return DomainError.InvalidState(
                "adjustment.below_reserved",
                $"Adjustment would leave {newOnHand} on hand but {Reserved} are reserved.");
        }

        if (newOnHand > int.MaxValue)
        {
            return DomainError.Validation("quantity.overflow", "Adjustment would overflow on-hand stock.");
        }

        OnHand = (int)newOnHand;
        Touch(now);
        return Result.Success();
    }

    private void Touch(DateTimeOffset now)
    {
        Version++;
        UpdatedAt = now;
    }
}
