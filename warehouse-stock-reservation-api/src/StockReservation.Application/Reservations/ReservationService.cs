using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using StockReservation.Application.Common;
using StockReservation.Application.Outbox;
using StockReservation.Application.Persistence;
using StockReservation.Domain;

namespace StockReservation.Application.Reservations;

/// <summary>
/// Reserves, confirms, releases and expires stock holds. Every write is one SaveChanges call, so the
/// stock change, its ledger movements and its outbox events commit together or not at all.
/// </summary>
public sealed partial class ReservationService(
    StockDbContext db,
    TimeProvider clock,
    IOptions<ReservationOptions> options,
    ILogger<ReservationService> logger)
{
    private readonly ReservationOptions _opts = options.Value;

    public async Task<Result<CreateReservationOutcome>> CreateAsync(
        CreateReservationCommand cmd,
        string actor,
        CancellationToken ct)
    {
        if (CreateReservationValidator.Validate(cmd, _opts.MaxLinesPerReservation, _opts.MaxHoldMinutes) is { } invalid)
        {
            return invalid;
        }

        var fingerprint = CreateReservationValidator.Fingerprint(cmd);
        if (await ReplayAsync(cmd.IdempotencyKey, fingerprint, ct) is { } replay)
        {
            return replay;
        }

        try
        {
            var (result, retries) = await ConcurrencyRetry.ExecuteAsync(
                db,
                _opts.MaxConcurrencyRetries,
                token => TryReserveAsync(cmd, fingerprint, actor, token),
                ct);
            if (result.IsSuccess)
            {
                LogReserved(logger, result.Value!.Id, cmd.OrderReference, cmd.WarehouseCode, retries);
                return new CreateReservationOutcome(result.Value!, Replayed: false, retries);
            }

            return result.Error!;
        }
        catch (DbUpdateException ex) when (ConcurrencyRetry.IsUniqueViolation(ex))
        {
            // Two requests with the same key raced; the loser returns the winner's reservation.
            db.ChangeTracker.Clear();
            return await ReplayAsync(cmd.IdempotencyKey, fingerprint, ct)
                ?? DomainError.Conflict("idempotency.race", "Concurrent request with the same key; retry.");
        }
    }

    public async Task<Result<Reservation>> ConfirmAsync(Guid id, string actor, CancellationToken ct)
    {
        var (result, _) = await ConcurrencyRetry.ExecuteAsync(
            db,
            _opts.MaxConcurrencyRetries,
            token => CloseAsync(id, actor, Transition.Confirm, token),
            ct);
        return result;
    }

    public async Task<Result<Reservation>> ReleaseAsync(Guid id, string actor, CancellationToken ct)
    {
        var (result, _) = await ConcurrencyRetry.ExecuteAsync(
            db,
            _opts.MaxConcurrencyRetries,
            token => CloseAsync(id, actor, Transition.Release, token),
            ct);
        return result;
    }

    /// <summary>Expires pending holds whose time is up and returns their stock. Returns the number expired.</summary>
    public async Task<int> ExpireDueAsync(int batchSize, CancellationToken ct)
    {
        var now = clock.GetUtcNow();
        var dueIds = await db.Reservations.AsNoTracking()
            .Where(r => r.Status == ReservationStatus.Pending && r.ExpiresAt <= now)
            .OrderBy(r => r.ExpiresAt)
            .Select(r => r.Id)
            .Take(batchSize)
            .ToListAsync(ct);

        var expired = 0;
        foreach (var id in dueIds)
        {
            // A confirm that wins the race makes this an invalid transition, which is fine to skip.
            var (result, _) = await ConcurrencyRetry.ExecuteAsync(
                db,
                _opts.MaxConcurrencyRetries,
                token => CloseAsync(id, "system:expiry", Transition.Expire, token),
                ct);
            if (result.IsSuccess)
            {
                expired++;
            }
        }

        if (expired > 0)
        {
            LogExpired(logger, expired);
        }

        return expired;
    }

    public async Task<Reservation?> FindAsync(Guid id, CancellationToken ct) =>
        await db.Reservations.AsNoTracking().Include(r => r.Lines).FirstOrDefaultAsync(r => r.Id == id, ct);

    public async Task<PagedResult<Reservation>> ListAsync(
        ReservationStatus? status,
        string? warehouse,
        PageRequest page,
        CancellationToken ct)
    {
        var query = db.Reservations.AsNoTracking();
        if (status is { } s)
        {
            query = query.Where(r => r.Status == s);
        }

        if (!string.IsNullOrWhiteSpace(warehouse))
        {
            var code = warehouse.Trim().ToUpperInvariant();
            query = query.Where(r => r.WarehouseCode == code);
        }

        var total = await query.CountAsync(ct);
        var items = await query
            .OrderByDescending(r => r.CreatedAt)
            .ThenBy(r => r.Id)
            .Skip(page.Skip)
            .Take(page.PageSize)
            .Include(r => r.Lines)
            .ToListAsync(ct);
        return new PagedResult<Reservation>(items, page.Page, page.PageSize, total);
    }

    private async Task<Result<CreateReservationOutcome>?> ReplayAsync(string key, string fingerprint, CancellationToken ct)
    {
        var existing = await db.Reservations.AsNoTracking()
            .Include(r => r.Lines)
            .FirstOrDefaultAsync(r => r.IdempotencyKey == key, ct);
        if (existing is null)
        {
            return null;
        }

        if (!string.Equals(existing.RequestFingerprint, fingerprint, StringComparison.Ordinal))
        {
            return DomainError.Conflict(
                "idempotency.key_reused",
                "This Idempotency-Key was already used with a different request body.");
        }

        return new CreateReservationOutcome(existing, Replayed: true, 0);
    }

    private async Task<Result<Reservation>> TryReserveAsync(
        CreateReservationCommand cmd,
        string fingerprint,
        string actor,
        CancellationToken ct)
    {
        var now = clock.GetUtcNow();
        var warehouse = cmd.WarehouseCode.Trim().ToUpperInvariant();
        var skus = cmd.Lines.Select(l => l.Sku.Trim().ToUpperInvariant()).ToList();
        var items = await db.StockItems
            .Where(s => s.WarehouseCode == warehouse && skus.Contains(s.Sku))
            .ToDictionaryAsync(s => s.Sku, StringComparer.Ordinal, ct);

        var missing = skus.Where(s => !items.ContainsKey(s)).ToList();
        if (missing.Count > 0)
        {
            return DomainError.NotFound(
                "stock.unknown_sku",
                $"Not stocked at {warehouse}: {string.Join(", ", missing)}.");
        }

        var lines = cmd.Lines
            .Select(l => new ReservationLine(l.Sku.Trim().ToUpperInvariant(), l.Quantity))
            .ToList();
        var hold = TimeSpan.FromMinutes(cmd.HoldMinutes ?? _opts.DefaultHoldMinutes);
        var reservation = new Reservation(
            cmd.OrderReference.Trim(), warehouse, lines, cmd.IdempotencyKey, fingerprint, actor, now, hold);

        // All-or-nothing: check every line before mutating any stock so a partial reservation never exists.
        var shortfalls = lines
            .Where(l => items[l.Sku].Available < l.Quantity)
            .Select(l => $"{l.Sku} (requested {l.Quantity}, available {items[l.Sku].Available})")
            .ToList();
        if (shortfalls.Count > 0)
        {
            return DomainError.Insufficient("stock.insufficient", $"Insufficient stock: {string.Join("; ", shortfalls)}.");
        }

        foreach (var line in lines)
        {
            var item = items[line.Sku];
            var wasBelow = item.IsBelowReorderPoint;
            var reserved = item.Reserve(line.Quantity, now);
            if (!reserved.IsSuccess)
            {
                return reserved.Error!;
            }

            db.Movements.Add(new StockMovement(item, MovementType.Reserve, line.Quantity, actor, now, reservation.Id));
            if (!wasBelow && item.IsBelowReorderPoint)
            {
                OutboxWriter.EnqueueStockLevel(db, IntegrationEvents.StockLow, item, now);
            }
        }

        db.Reservations.Add(reservation);
        OutboxWriter.EnqueueReservation(db, IntegrationEvents.ReservationCreated, reservation, now);
        await db.SaveChangesAsync(ct);
        return reservation;
    }

    private enum Transition
    {
        Confirm,
        Release,
        Expire,
    }

    private async Task<Result<Reservation>> CloseAsync(Guid id, string actor, Transition transition, CancellationToken ct)
    {
        var now = clock.GetUtcNow();
        var reservation = await db.Reservations.Include(r => r.Lines).FirstOrDefaultAsync(r => r.Id == id, ct);
        if (reservation is null)
        {
            return DomainError.NotFound("reservation.not_found", $"Reservation {id} does not exist.");
        }

        var closed = transition switch
        {
            Transition.Confirm => reservation.Confirm(now),
            Transition.Release => reservation.Release(now),
            _ => reservation.Expire(now),
        };
        if (!closed.IsSuccess)
        {
            return closed.Error!;
        }

        var skus = reservation.Lines.Select(l => l.Sku).ToList();
        var items = await db.StockItems
            .Where(s => s.WarehouseCode == reservation.WarehouseCode && skus.Contains(s.Sku))
            .ToDictionaryAsync(s => s.Sku, StringComparer.Ordinal, ct);

        var (movementType, eventType) = transition switch
        {
            Transition.Confirm => (MovementType.Allocate, IntegrationEvents.ReservationConfirmed),
            Transition.Release => (MovementType.Release, IntegrationEvents.ReservationReleased),
            _ => (MovementType.Expire, IntegrationEvents.ReservationExpired),
        };

        foreach (var line in reservation.Lines)
        {
            var item = items[line.Sku];
            var applied = transition == Transition.Confirm
                ? item.Allocate(line.Quantity, now)
                : item.Release(line.Quantity, now);
            if (!applied.IsSuccess)
            {
                return applied.Error!;
            }

            db.Movements.Add(new StockMovement(item, movementType, -line.Quantity, actor, now, reservation.Id));
        }

        OutboxWriter.EnqueueReservation(db, eventType, reservation, now);
        await db.SaveChangesAsync(ct);
        return reservation;
    }

    [LoggerMessage(
        Level = LogLevel.Information,
        Message = "Reserved {ReservationId} for order {OrderReference} at {Warehouse} after {Retries} concurrency retries")]
    private static partial void LogReserved(ILogger logger, Guid reservationId, string orderReference, string warehouse, int retries);

    [LoggerMessage(Level = LogLevel.Information, Message = "Expired {Count} overdue reservations")]
    private static partial void LogExpired(ILogger logger, int count);
}
