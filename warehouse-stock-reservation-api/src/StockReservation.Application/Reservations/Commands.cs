using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using StockReservation.Domain;

namespace StockReservation.Application.Reservations;

public sealed record ReservationLineRequest(string Sku, int Quantity);

public sealed record CreateReservationCommand(
    string OrderReference,
    string WarehouseCode,
    IReadOnlyList<ReservationLineRequest> Lines,
    string IdempotencyKey,
    int? HoldMinutes = null);

/// <summary>Outcome of a create call; <see cref="Replayed"/> is true when an idempotency key matched.</summary>
public sealed record CreateReservationOutcome(Reservation Reservation, bool Replayed, int ConcurrencyRetries);

public static class CreateReservationValidator
{
    public static DomainError? Validate(CreateReservationCommand cmd, int maxLines, int maxHoldMinutes)
    {
        if (string.IsNullOrWhiteSpace(cmd.IdempotencyKey) || cmd.IdempotencyKey.Length is < 8 or > 100)
        {
            return DomainError.Validation("idempotency_key.invalid", "Idempotency-Key must be 8-100 characters.");
        }

        if (string.IsNullOrWhiteSpace(cmd.OrderReference) || cmd.OrderReference.Length > 64)
        {
            return DomainError.Validation("order_reference.invalid", "Order reference must be 1-64 characters.");
        }

        if (string.IsNullOrWhiteSpace(cmd.WarehouseCode) || cmd.WarehouseCode.Length > 8)
        {
            return DomainError.Validation("warehouse.invalid", "Warehouse code must be 1-8 characters.");
        }

        if (cmd.Lines is null || cmd.Lines.Count == 0)
        {
            return DomainError.Validation("lines.empty", "A reservation needs at least one line.");
        }

        if (cmd.Lines.Count > maxLines)
        {
            return DomainError.Validation("lines.too_many", $"A reservation may have at most {maxLines} lines.");
        }

        if (cmd.Lines.Any(l => string.IsNullOrWhiteSpace(l.Sku) || l.Sku.Length > 32))
        {
            return DomainError.Validation("line.sku_invalid", "Every line needs a SKU of 1-32 characters.");
        }

        if (cmd.Lines.Any(l => l.Quantity is <= 0 or > 10_000))
        {
            return DomainError.Validation("line.quantity_invalid", "Line quantities must be between 1 and 10,000.");
        }

        if (cmd.Lines.GroupBy(l => l.Sku.Trim().ToUpperInvariant()).Any(g => g.Count() > 1))
        {
            return DomainError.Validation("lines.duplicate_sku", "Each SKU may appear only once per reservation.");
        }

        if (cmd.HoldMinutes is { } hold && (hold < 1 || hold > maxHoldMinutes))
        {
            return DomainError.Validation("hold.invalid", $"Hold must be between 1 and {maxHoldMinutes} minutes.");
        }

        return null;
    }

    /// <summary>Canonical SHA-256 of the request body, independent of line order and SKU casing.</summary>
    public static string Fingerprint(CreateReservationCommand cmd)
    {
        var lines = cmd.Lines
            .Select(l => $"{l.Sku.Trim().ToUpperInvariant()}:{l.Quantity.ToString(CultureInfo.InvariantCulture)}")
            .Order(StringComparer.Ordinal);
        var hold = cmd.HoldMinutes?.ToString(CultureInfo.InvariantCulture) ?? "-";
        var canonical = $"{cmd.WarehouseCode.Trim().ToUpperInvariant()}|{cmd.OrderReference.Trim()}|{hold}|{string.Join(',', lines)}";
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical)));
    }
}
