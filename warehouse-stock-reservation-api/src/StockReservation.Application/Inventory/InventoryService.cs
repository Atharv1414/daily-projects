using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using StockReservation.Application.Common;
using StockReservation.Application.Outbox;
using StockReservation.Application.Persistence;
using StockReservation.Domain;

namespace StockReservation.Application.Inventory;

public sealed record StockQuery(string? Warehouse, string? SkuPrefix, bool BelowReorderOnly, PageRequest Page);

public sealed record StockView(
    string WarehouseCode,
    string Sku,
    string Description,
    int OnHand,
    int Reserved,
    int Available,
    int ReorderPoint,
    decimal UnitCostGbp,
    int Version,
    DateTimeOffset UpdatedAt)
{
    public static StockView From(StockItem s) => new(
        s.WarehouseCode,
        s.Sku,
        s.Description,
        s.OnHand,
        s.Reserved,
        s.Available,
        s.ReorderPoint,
        s.UnitCostPence / 100m,
        s.Version,
        s.UpdatedAt);
}

public sealed record WarehouseValuation(
    string WarehouseCode,
    int SkuCount,
    long UnitsOnHand,
    long UnitsReserved,
    decimal StockValueGbp,
    decimal ReservedValueGbp,
    int SkusBelowReorder);

/// <summary>Goods-in, stock-count adjustments and read models over the stock ledger.</summary>
public sealed class InventoryService(StockDbContext db, TimeProvider clock, IOptions<ReservationOptions> options)
{
    private readonly int _maxRetries = options.Value.MaxConcurrencyRetries;

    public async Task<PagedResult<StockView>> SearchAsync(StockQuery q, CancellationToken ct)
    {
        var query = db.StockItems.AsNoTracking();
        if (!string.IsNullOrWhiteSpace(q.Warehouse))
        {
            var code = q.Warehouse.Trim().ToUpperInvariant();
            query = query.Where(s => s.WarehouseCode == code);
        }

        if (!string.IsNullOrWhiteSpace(q.SkuPrefix))
        {
            // LIKE with an escaped prefix keeps the (WarehouseCode, Sku) index usable.
            var prefix = EscapeLike(q.SkuPrefix.Trim().ToUpperInvariant());
            query = query.Where(s => EF.Functions.Like(s.Sku, prefix + "%", "\\"));
        }

        if (q.BelowReorderOnly)
        {
            query = query.Where(s => s.OnHand - s.Reserved <= s.ReorderPoint);
        }

        var total = await query.CountAsync(ct);
        var rows = await query
            .OrderBy(s => s.WarehouseCode)
            .ThenBy(s => s.Sku)
            .Skip(q.Page.Skip)
            .Take(q.Page.PageSize)
            .ToListAsync(ct);
        return new PagedResult<StockView>([.. rows.Select(StockView.From)], q.Page.Page, q.Page.PageSize, total);
    }

    public async Task<StockView?> GetAsync(string warehouse, string sku, CancellationToken ct)
    {
        var item = await FindAsync(warehouse, sku, tracked: false, ct);
        return item is null ? null : StockView.From(item);
    }

    public async Task<Result<StockView>> ReceiveAsync(
        string warehouse,
        string sku,
        int quantity,
        string? reference,
        string actor,
        CancellationToken ct)
    {
        var (result, _) = await ConcurrencyRetry.ExecuteAsync<StockView>(
            db,
            _maxRetries,
            async token =>
            {
                var now = clock.GetUtcNow();
                var item = await FindAsync(warehouse, sku, tracked: true, token);
                if (item is null)
                {
                    return NotStocked(warehouse, sku);
                }

                var received = item.Receive(quantity, now);
                if (!received.IsSuccess)
                {
                    return received.Error!;
                }

                db.Movements.Add(new StockMovement(item, MovementType.Receipt, quantity, actor, now, note: reference));
                OutboxWriter.EnqueueStockLevel(db, IntegrationEvents.StockReceived, item, now);
                await db.SaveChangesAsync(token);
                return StockView.From(item);
            },
            ct);
        return result;
    }

    public async Task<Result<StockView>> AdjustAsync(
        string warehouse,
        string sku,
        int delta,
        string reason,
        string actor,
        CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(reason) || reason.Length > 200)
        {
            return DomainError.Validation("adjustment.reason_required", "An adjustment needs a reason (max 200 chars).");
        }

        var (result, _) = await ConcurrencyRetry.ExecuteAsync<StockView>(
            db,
            _maxRetries,
            async token =>
            {
                var now = clock.GetUtcNow();
                var item = await FindAsync(warehouse, sku, tracked: true, token);
                if (item is null)
                {
                    return NotStocked(warehouse, sku);
                }

                var wasBelow = item.IsBelowReorderPoint;
                var adjusted = item.Adjust(delta, now);
                if (!adjusted.IsSuccess)
                {
                    return adjusted.Error!;
                }

                db.Movements.Add(new StockMovement(item, MovementType.Adjustment, delta, actor, now, note: reason));
                if (!wasBelow && item.IsBelowReorderPoint)
                {
                    OutboxWriter.EnqueueStockLevel(db, IntegrationEvents.StockLow, item, now);
                }

                await db.SaveChangesAsync(token);
                return StockView.From(item);
            },
            ct);
        return result;
    }

    public async Task<PagedResult<StockMovement>?> MovementsAsync(
        string warehouse,
        string sku,
        PageRequest page,
        CancellationToken ct)
    {
        var item = await FindAsync(warehouse, sku, tracked: false, ct);
        if (item is null)
        {
            return null;
        }

        var query = db.Movements.AsNoTracking().Where(m => m.StockItemId == item.Id);
        var total = await query.CountAsync(ct);
        var rows = await query
            .OrderByDescending(m => m.OccurredAt)
            .ThenBy(m => m.Id)
            .Skip(page.Skip)
            .Take(page.PageSize)
            .ToListAsync(ct);
        return new PagedResult<StockMovement>(rows, page.Page, page.PageSize, total);
    }

    /// <summary>Stock value per warehouse in pounds sterling, aggregated in SQL.</summary>
    public async Task<IReadOnlyList<WarehouseValuation>> ValuationAsync(CancellationToken ct)
    {
        var rows = await db.StockItems.AsNoTracking()
            .GroupBy(s => s.WarehouseCode)
            .Select(g => new
            {
                Warehouse = g.Key,
                Skus = g.Count(),
                OnHand = g.Sum(s => (long)s.OnHand),
                Reserved = g.Sum(s => (long)s.Reserved),
                ValuePence = g.Sum(s => s.OnHand * s.UnitCostPence),
                ReservedPence = g.Sum(s => s.Reserved * s.UnitCostPence),
                Below = g.Count(s => s.OnHand - s.Reserved <= s.ReorderPoint),
            })
            .OrderBy(r => r.Warehouse)
            .ToListAsync(ct);
        return [.. rows.Select(r => new WarehouseValuation(
            r.Warehouse, r.Skus, r.OnHand, r.Reserved, r.ValuePence / 100m, r.ReservedPence / 100m, r.Below))];
    }

    /// <summary>
    /// Reconciliation check: replays the movement ledger and compares it with current stock.
    /// Returns the SKUs whose ledger and balance disagree (should always be empty).
    /// </summary>
    public async Task<IReadOnlyList<string>> ReconcileAsync(CancellationToken ct)
    {
        var ledger = await db.Movements.AsNoTracking()
            .GroupBy(m => new { m.StockItemId, m.Type })
            .Select(g => new { g.Key.StockItemId, g.Key.Type, Qty = g.Sum(m => m.Quantity) })
            .ToListAsync(ct);
        var reservedByItem = ledger
            .Where(l => l.Type is MovementType.Reserve or MovementType.Release or MovementType.Expire or MovementType.Allocate)
            .GroupBy(l => l.StockItemId)
            .ToDictionary(g => g.Key, g => g.Sum(x => x.Qty));
        var items = await db.StockItems.AsNoTracking().ToListAsync(ct);
        return [.. items
            .Where(i => reservedByItem.GetValueOrDefault(i.Id) != i.Reserved)
            .Select(i => $"{i.WarehouseCode}/{i.Sku}")];
    }

    private static DomainError NotStocked(string warehouse, string sku) =>
        DomainError.NotFound("stock.not_found", $"{sku} is not stocked at {warehouse}.");

    private static string EscapeLike(string value) =>
        value.Replace("\\", "\\\\", StringComparison.Ordinal)
            .Replace("%", "\\%", StringComparison.Ordinal)
            .Replace("_", "\\_", StringComparison.Ordinal);

    private Task<StockItem?> FindAsync(string warehouse, string sku, bool tracked, CancellationToken ct)
    {
        var code = warehouse.Trim().ToUpperInvariant();
        var normalisedSku = sku.Trim().ToUpperInvariant();
        var source = tracked ? db.StockItems : db.StockItems.AsNoTracking();
        return source.FirstOrDefaultAsync(s => s.WarehouseCode == code && s.Sku == normalisedSku, ct);
    }
}
