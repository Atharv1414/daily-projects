namespace StockReservation.Domain;

public enum ReservationStatus
{
    Pending,
    Confirmed,
    Released,
    Expired,
}

/// <summary>One SKU and quantity within a reservation.</summary>
public sealed class ReservationLine
{
    private ReservationLine() => Sku = string.Empty;

    public ReservationLine(string sku, int quantity)
    {
        Id = Guid.NewGuid();
        Sku = sku;
        Quantity = quantity;
    }

    public Guid Id { get; private set; }

    public Guid ReservationId { get; private set; }

    public string Sku { get; private set; }

    public int Quantity { get; private set; }
}

/// <summary>
/// A time-limited hold on stock for an order. State machine:
/// Pending → Confirmed (picked) | Released (cancelled) | Expired (hold timed out).
/// </summary>
public sealed class Reservation
{
    private readonly List<ReservationLine> _lines = [];

    private Reservation()
    {
        OrderReference = string.Empty;
        WarehouseCode = string.Empty;
        IdempotencyKey = string.Empty;
        RequestFingerprint = string.Empty;
        CreatedBy = string.Empty;
    }

    public Reservation(
        string orderReference,
        string warehouseCode,
        IEnumerable<ReservationLine> lines,
        string idempotencyKey,
        string requestFingerprint,
        string createdBy,
        DateTimeOffset now,
        TimeSpan holdFor)
    {
        Id = Guid.NewGuid();
        OrderReference = orderReference;
        WarehouseCode = warehouseCode;
        IdempotencyKey = idempotencyKey;
        RequestFingerprint = requestFingerprint;
        CreatedBy = createdBy;
        CreatedAt = now;
        ExpiresAt = now + holdFor;
        Status = ReservationStatus.Pending;
        _lines.AddRange(lines);
    }

    public Guid Id { get; private set; }

    public string OrderReference { get; private set; }

    public string WarehouseCode { get; private set; }

    public ReservationStatus Status { get; private set; }

    public string IdempotencyKey { get; private set; }

    /// <summary>Hash of the request body, so a reused idempotency key with a different body is rejected.</summary>
    public string RequestFingerprint { get; private set; }

    public string CreatedBy { get; private set; }

    public DateTimeOffset CreatedAt { get; private set; }

    public DateTimeOffset ExpiresAt { get; private set; }

    public DateTimeOffset? ClosedAt { get; private set; }

    public int Version { get; private set; }

    public IReadOnlyList<ReservationLine> Lines => _lines;

    public int TotalUnits => _lines.Sum(l => l.Quantity);

    public bool IsExpiredAt(DateTimeOffset now) => Status == ReservationStatus.Pending && now >= ExpiresAt;

    public Result Confirm(DateTimeOffset now)
    {
        if (Status != ReservationStatus.Pending)
        {
            return InvalidTransition(ReservationStatus.Confirmed);
        }

        if (now >= ExpiresAt)
        {
            return DomainError.InvalidState("reservation.expired", "The reservation hold has expired.");
        }

        return Close(ReservationStatus.Confirmed, now);
    }

    public Result Release(DateTimeOffset now) =>
        Status == ReservationStatus.Pending ? Close(ReservationStatus.Released, now) : InvalidTransition(ReservationStatus.Released);

    public Result Expire(DateTimeOffset now)
    {
        if (Status != ReservationStatus.Pending)
        {
            return InvalidTransition(ReservationStatus.Expired);
        }

        return now < ExpiresAt
            ? DomainError.InvalidState("reservation.not_due", "The reservation has not reached its expiry time.")
            : Close(ReservationStatus.Expired, now);
    }

    private Result Close(ReservationStatus status, DateTimeOffset now)
    {
        Status = status;
        ClosedAt = now;
        Version++;
        return Result.Success();
    }

    private DomainError InvalidTransition(ReservationStatus target) =>
        DomainError.InvalidState(
            "reservation.invalid_transition",
            $"Cannot move reservation from {Status} to {target}.");
}
