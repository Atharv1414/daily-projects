using System.Security.Claims;
using StockReservation.Api.Auth;
using StockReservation.Application.Common;
using StockReservation.Application.Inventory;

namespace StockReservation.Api.Endpoints;

public static class StockEndpoints
{
    public static IEndpointRouteBuilder MapStockEndpoints(this IEndpointRouteBuilder app)
    {
        var stock = app.MapGroup("/api/stock").WithTags("Stock").RequireAuthorization(Policies.CanRead);

        stock.MapGet("/", async (
                string? warehouse,
                string? skuPrefix,
                bool? belowReorder,
                int? page,
                int? pageSize,
                InventoryService inventory,
                CancellationToken ct) =>
            Results.Ok(await inventory.SearchAsync(
                new StockQuery(warehouse, skuPrefix, belowReorder ?? false, PageRequest.Create(page, pageSize)), ct)))
            .WithSummary("Search stock with filters and pagination");

        stock.MapGet("/valuation", async (InventoryService inventory, CancellationToken ct) =>
                Results.Ok(await inventory.ValuationAsync(ct)))
            .WithSummary("Stock value per warehouse (GBP)");

        stock.MapGet("/{warehouse}/{sku}", async (string warehouse, string sku, InventoryService inventory, CancellationToken ct) =>
                await inventory.GetAsync(warehouse, sku, ct) is { } view ? Results.Ok(view) : Results.NotFound())
            .WithSummary("Get one stock line");

        stock.MapGet("/{warehouse}/{sku}/movements", async (
                string warehouse,
                string sku,
                int? page,
                int? pageSize,
                InventoryService inventory,
                CancellationToken ct) =>
            await inventory.MovementsAsync(warehouse, sku, PageRequest.Create(page, pageSize), ct) is { } result
                ? Results.Ok(new PagedResult<MovementResponse>(
                    [.. result.Items.Select(MovementResponse.From)], result.Page, result.PageSize, result.TotalCount))
                : Results.NotFound())
            .WithSummary("Ledger of movements for one stock line, newest first");

        stock.MapPost("/{warehouse}/{sku}/receipts", async (
                string warehouse,
                string sku,
                ReceiptRequest request,
                ClaimsPrincipal user,
                InventoryService inventory,
                CancellationToken ct) =>
            (await inventory.ReceiveAsync(warehouse, sku, request.Quantity, request.Reference, user.Identity!.Name!, ct))
                .ToHttp(Results.Ok))
            .RequireAuthorization(Policies.CanPlan)
            .RequireRateLimiting(RateLimitPolicies.Writes)
            .WithSummary("Book goods-in against a stock line");

        stock.MapPost("/{warehouse}/{sku}/adjustments", async (
                string warehouse,
                string sku,
                AdjustmentRequest request,
                ClaimsPrincipal user,
                InventoryService inventory,
                CancellationToken ct) =>
            (await inventory.AdjustAsync(warehouse, sku, request.Delta, request.Reason, user.Identity!.Name!, ct))
                .ToHttp(Results.Ok))
            .RequireAuthorization(Policies.CanAdmin)
            .RequireRateLimiting(RateLimitPolicies.Writes)
            .WithSummary("Stock-count correction (admin only)");

        return app;
    }
}
