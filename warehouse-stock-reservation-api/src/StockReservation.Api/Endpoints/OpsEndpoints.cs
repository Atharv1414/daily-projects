using StockReservation.Api.Auth;
using StockReservation.Application.Inventory;
using StockReservation.Application.Outbox;
using StockReservation.Application.Reservations;

namespace StockReservation.Api.Endpoints;

public static class OpsEndpoints
{
    public static IEndpointRouteBuilder MapOpsEndpoints(this IEndpointRouteBuilder app)
    {
        var ops = app.MapGroup("/api/ops").WithTags("Operations").RequireAuthorization(Policies.CanAdmin);

        ops.MapGet("/outbox", async (OutboxDispatcher dispatcher, CancellationToken ct) =>
                Results.Ok(await dispatcher.GetStatsAsync(ct)))
            .WithSummary("Outbox backlog and dead-letter counts");

        ops.MapPost("/outbox/dispatch", async (OutboxDispatcher dispatcher, CancellationToken ct) =>
                Results.Ok(await dispatcher.DispatchBatchAsync(ct)))
            .WithSummary("Publish one outbox batch now");

        ops.MapPost("/expire", async (ReservationService service, CancellationToken ct) =>
                Results.Ok(new { expired = await service.ExpireDueAsync(500, ct) }))
            .WithSummary("Run the expiry sweep now");

        ops.MapGet("/reconcile", async (InventoryService inventory, CancellationToken ct) =>
            {
                var mismatches = await inventory.ReconcileAsync(ct);
                return Results.Ok(new { consistent = mismatches.Count == 0, mismatches });
            })
            .WithSummary("Check reserved balances against the movement ledger");

        return app;
    }
}
