using System.Security.Claims;
using Microsoft.AspNetCore.Mvc;
using StockReservation.Api.Auth;
using StockReservation.Application.Common;
using StockReservation.Application.Reservations;
using StockReservation.Domain;

namespace StockReservation.Api.Endpoints;

public static class ReservationEndpoints
{
    public const string IdempotencyHeader = "Idempotency-Key";

    public static IEndpointRouteBuilder MapReservationEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/api/reservations").WithTags("Reservations").RequireAuthorization(Policies.CanRead);

        group.MapPost("/", async (
                CreateReservationRequest request,
                [FromHeader(Name = IdempotencyHeader)] string? idempotencyKey,
                ClaimsPrincipal user,
                ReservationService service,
                HttpContext http,
                CancellationToken ct) =>
            {
                if (string.IsNullOrWhiteSpace(idempotencyKey))
                {
                    return DomainError.Validation("idempotency_key.missing", $"The {IdempotencyHeader} header is required.")
                        .ToProblem();
                }

                var command = new CreateReservationCommand(
                    request.OrderReference, request.WarehouseCode, request.Lines ?? [], idempotencyKey, request.HoldMinutes);
                var result = await service.CreateAsync(command, user.Identity!.Name!, ct);
                return result.ToHttp(outcome =>
                {
                    var body = ReservationResponse.From(outcome.Reservation);
                    http.Response.Headers["Idempotent-Replayed"] = outcome.Replayed ? "true" : "false";
                    return outcome.Replayed
                        ? Results.Ok(body)
                        : Results.Created($"/api/reservations/{body.Id}", body);
                });
            })
            .RequireAuthorization(Policies.CanPlan)
            .RequireRateLimiting(RateLimitPolicies.Writes)
            .WithSummary("Reserve stock for an order (all lines or nothing). Requires an Idempotency-Key header.");

        group.MapGet("/", async (
                ReservationStatus? status,
                string? warehouse,
                int? page,
                int? pageSize,
                ReservationService service,
                CancellationToken ct) =>
            {
                var result = await service.ListAsync(status, warehouse, PageRequest.Create(page, pageSize), ct);
                return Results.Ok(new PagedResult<ReservationResponse>(
                    [.. result.Items.Select(ReservationResponse.From)], result.Page, result.PageSize, result.TotalCount));
            })
            .WithSummary("List reservations, newest first");

        group.MapGet("/{id:guid}", async (Guid id, ReservationService service, CancellationToken ct) =>
                await service.FindAsync(id, ct) is { } r ? Results.Ok(ReservationResponse.From(r)) : Results.NotFound())
            .WithSummary("Get a reservation");

        group.MapPost("/{id:guid}/confirm", async (Guid id, ClaimsPrincipal user, ReservationService service, CancellationToken ct) =>
                (await service.ConfirmAsync(id, user.Identity!.Name!, ct)).ToHttp(r => Results.Ok(ReservationResponse.From(r))))
            .RequireAuthorization(Policies.CanPick)
            .RequireRateLimiting(RateLimitPolicies.Writes)
            .WithSummary("Confirm a pick: reserved units leave stock");

        group.MapPost("/{id:guid}/release", async (Guid id, ClaimsPrincipal user, ReservationService service, CancellationToken ct) =>
                (await service.ReleaseAsync(id, user.Identity!.Name!, ct)).ToHttp(r => Results.Ok(ReservationResponse.From(r))))
            .RequireAuthorization(Policies.CanPlan)
            .RequireRateLimiting(RateLimitPolicies.Writes)
            .WithSummary("Cancel a reservation and return its stock");

        return app;
    }
}
