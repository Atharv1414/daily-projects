using FareEngine.Api.Auth;
using FareEngine.Application.Persistence;
using FareEngine.Application.Settlement;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.EntityFrameworkCore;

namespace FareEngine.Api.Endpoints;

public static class OpsEndpoints
{
    public static void MapOps(this IEndpointRouteBuilder app)
    {
        var ops = app.MapGroup("/v1").RequireAuthorization(Policies.Finance).WithTags("Finance");
        ops.MapPost("/settlements/{date}", SettleAsync).WithSummary("Close a service day. Running it twice does nothing.");
        ops.MapGet("/queue", QueueAsync).WithSummary("Rating backlog, including jobs parked after repeated failures.");
    }

    private static async Task<Ok<SettlementView>> SettleAsync(DateOnly date, SettlementService service, CancellationToken ct)
    {
        var s = await service.SettleAsync(date, ct);
        return TypedResults.Ok(new SettlementView(s.Date, s.AlreadyDone, s.Lines, s.Collected.Pence, s.Refunded.Pence));
    }

    private static async Task<Ok<QueueView>> QueueAsync(FareDbContext db, CancellationToken ct)
    {
        var parked = await db.Jobs.AsNoTracking().Where(j => j.Dead)
            .OrderBy(j => j.DueAtMs)
            .Take(50)
            .Select(j => new ParkedJob(j.CardToken, j.WeekStart, j.Attempts, j.LastError))
            .ToListAsync(ct);
        return TypedResults.Ok(new QueueView(await db.Jobs.CountAsync(j => !j.Dead, ct), parked));
    }

    public sealed record ParkedJob(string CardToken, DateOnly WeekStart, int Attempts, string? LastError);

    public sealed record QueueView(int Waiting, IReadOnlyList<ParkedJob> Parked);
}
