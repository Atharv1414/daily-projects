using StockReservation.Application.Reservations;
using StockReservation.Domain;

namespace StockReservation.Api.Endpoints;

public sealed record TokenRequest(string Username, string Password);

public sealed record CreateReservationRequest(
    string OrderReference,
    string WarehouseCode,
    IReadOnlyList<ReservationLineRequest> Lines,
    int? HoldMinutes);

public sealed record ReceiptRequest(int Quantity, string? Reference);

public sealed record AdjustmentRequest(int Delta, string Reason);

public sealed record ReservationResponse(
    Guid Id,
    string OrderReference,
    string WarehouseCode,
    string Status,
    DateTimeOffset CreatedAt,
    DateTimeOffset ExpiresAt,
    DateTimeOffset? ClosedAt,
    string CreatedBy,
    int TotalUnits,
    IReadOnlyList<ReservationLineDto> Lines)
{
    public static ReservationResponse From(Reservation r) => new(
        r.Id,
        r.OrderReference,
        r.WarehouseCode,
        r.Status.ToString(),
        r.CreatedAt,
        r.ExpiresAt,
        r.ClosedAt,
        r.CreatedBy,
        r.TotalUnits,
        [.. r.Lines.Select(l => new ReservationLineDto(l.Sku, l.Quantity))]);
}

public sealed record MovementResponse(
    string Type,
    int Quantity,
    int OnHandAfter,
    int ReservedAfter,
    string Actor,
    DateTimeOffset OccurredAt,
    Guid? ReservationId,
    string? Note)
{
    public static MovementResponse From(StockMovement m) =>
        new(m.Type.ToString(), m.Quantity, m.OnHandAfter, m.ReservedAfter, m.Actor, m.OccurredAt, m.ReservationId, m.Note);
}
