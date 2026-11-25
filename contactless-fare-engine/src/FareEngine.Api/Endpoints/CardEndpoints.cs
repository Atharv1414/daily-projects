using System.Security.Claims;
using FareEngine.Api.Auth;
using FareEngine.Application.Persistence;
using FareEngine.Application.Rating;
using FareEngine.Application.Taps;
using FareEngine.Domain;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.EntityFrameworkCore;

namespace FareEngine.Api.Endpoints;

public static class CardEndpoints
{
    public static void MapCards(this IEndpointRouteBuilder app)
    {
        var cards = app.MapGroup("/v1/cards/{token}").RequireAuthorization(Policies.Agent).WithTags("Cards");
        cards.MapGet("/weeks/{week}", GetWeekAsync).WithSummary("A week's journeys, what each cost and why.");
        cards.MapGet("/ledger", GetLedgerAsync).WithSummary("Money movements, oldest first, paged by id.");
        cards.MapPost("/corrections", CorrectAsync).WithSummary("Add a missed tap on a rider's behalf.");
    }

    private static async Task<Results<Ok<StatementView>, ProblemHttpResult>> GetWeekAsync(
        string token, DateOnly week, WeekRater rater, Network network, CancellationToken ct)
    {
        if (ServiceCalendar.WeekStart(week) != week)
        {
            return TypedResults.Problem("A week is named by its Monday.", statusCode: StatusCodes.Status400BadRequest);
        }

        return TypedResults.Ok(StatementView.From(await rater.PreviewAsync(token, week, ct), network));
    }

    private static async Task<Ok<LedgerPage>> GetLedgerAsync(
        string token, FareDbContext db, CancellationToken ct, long after = 0, int limit = 50)
    {
        limit = Math.Clamp(limit, 1, 200);
        var rows = await db.Ledger.AsNoTracking()
            .Where(e => e.CardToken == token && e.Id > after)
            .OrderBy(e => e.Id)
            .Take(limit + 1)
            .ToListAsync(ct);
        var page = rows.Take(limit)
            .Select(e => new LedgerView(
                e.Id, e.ServiceDate, e.AmountPence, e.Kind, DateTimeOffset.FromUnixTimeMilliseconds(e.PostedAtMs), e.SettlementLineId is not null))
            .ToList();
        return TypedResults.Ok(new LedgerPage(page, rows.Count > limit ? page[^1].Id : null));
    }

    private static async Task<Results<Ok<TapResult>, ProblemHttpResult>> CorrectAsync(
        string token, CorrectionRequest request, ClaimsPrincipal user, TapIngestion ingestion, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(request.Reason) || request.Reason.Length > 200)
        {
            return TypedResults.Problem("Give a reason of up to 200 characters.", statusCode: StatusCodes.Status400BadRequest);
        }

        var tap = new IncomingTap(request.Id, token, request.PlaceId, request.Kind, request.OccurredAt);
        var results = await ingestion.IngestAsync(
            [tap], user.Identity!.Name!, TapSource.StaffCorrection, request.Reason.Trim(), ct);
        return results[0].Outcome switch
        {
            TapOutcome.Rejected => TypedResults.Problem(results[0].Reason, statusCode: StatusCodes.Status400BadRequest),
            TapOutcome.Conflict => TypedResults.Problem(results[0].Reason, statusCode: StatusCodes.Status409Conflict),
            _ => TypedResults.Ok(results[0]),
        };
    }
}
