using System.Security.Claims;
using System.Text.Json;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.Extensions.Options;
using Rollout.Api.Auth;
using Rollout.Application;
using Rollout.Application.Exposures;
using Rollout.Application.Snapshots;
using Rollout.Domain;

namespace Rollout.Api.Endpoints;

public sealed record EvaluateRequest(JsonElement Context, IReadOnlyList<string>? Flags = null, bool Track = true);

public sealed record EvaluateResponse(string Environment, string ETag, IReadOnlyList<Evaluation> Evaluations);

public sealed record ExposureInput(string Flag, string Variant, DateTimeOffset? At = null);

public sealed record ExposureBatch(IReadOnlyList<ExposureInput> Exposures);

public sealed record ExposureReceipt(int Accepted, int Dropped, int Rejected);

public sealed record OpsStats(long ExposuresAccepted, long ExposuresDropped, int ExposuresPending, long SnapshotBuilds);

/// <summary>
/// Endpoints for SDKs in TV, phone and web apps. The environment comes from the key, never the URL,
/// so a leaked staging key cannot read production.
/// </summary>
public static class SdkEndpoints
{
    public const string RateLimitPolicy = "sdk";

    public static IEndpointRouteBuilder MapSdk(this IEndpointRouteBuilder app)
    {
        var sdk = app.MapGroup("/v1/sdk")
            .RequireAuthorization(Policies.Sdk)
            .RequireRateLimiting(RateLimitPolicy)
            .WithTags("SDK");
        sdk.MapGet("/snapshot", SnapshotAsync)
            .WithSummary("All flags for this key's environment. Send If-None-Match to get 304 when nothing changed.");
        sdk.MapPost("/evaluate", EvaluateAsync)
            .WithSummary("Server-side evaluation for thin clients. Records exposures for experiment flags unless track is false.");
        sdk.MapPost("/exposures", RecordExposuresAsync)
            .WithSummary("Exposures from SDKs that evaluate locally. Accepted into a bounded buffer; 202 even when some are dropped.");

        app.MapGet("/v1/ops/stats", (ExposureBuffer buffer, SnapshotCache cache) =>
                new OpsStats(buffer.Accepted, buffer.Dropped, buffer.Pending, cache.Builds))
            .RequireAuthorization(Policies.Read)
            .WithTags("Ops");
        return app;
    }

    private static async Task<IResult> SnapshotAsync(ClaimsPrincipal user, SnapshotCache cache, HttpRequest request, HttpResponse response, CancellationToken ct)
    {
        var snapshot = await cache.GetAsync(Environment(user), ct);
        response.Headers.ETag = snapshot.ETag;
        response.Headers.CacheControl = "no-cache";
        if (request.Headers.IfNoneMatch.Any(v => v is not null && v.Split(',').Select(t => t.Trim()).Contains(snapshot.ETag, StringComparer.Ordinal)))
        {
            return TypedResults.StatusCode(StatusCodes.Status304NotModified);
        }

        return TypedResults.Bytes(snapshot.Json, "application/json");
    }

    private static async Task<Ok<EvaluateResponse>> EvaluateAsync(
        EvaluateRequest body, ClaimsPrincipal user, SnapshotCache cache, ExposureBuffer exposures, TimeProvider clock, CancellationToken ct)
    {
        var environment = Environment(user);
        var snapshot = await cache.GetAsync(environment, ct);
        var context = EvaluationContext.FromJson(body.Context);
        var now = clock.GetUtcNow();
        var results = body.Flags is { Count: > 0 } wanted
            ? [.. wanted.Distinct(StringComparer.Ordinal).Select(k => snapshot.Flags.Evaluate(k, context, now))]
            : snapshot.Flags.EvaluateAll(context, now);
        if (body.Track)
        {
            exposures.Offer(results.Where(r => r.InExperiment).Select(r => new Exposure(environment, r.FlagKey, r.Variant, now)));
        }

        return TypedResults.Ok(new EvaluateResponse(environment, snapshot.ETag, results));
    }

    private static async Task<Results<Accepted<ExposureReceipt>, BadRequest<string>>> RecordExposuresAsync(
        ExposureBatch body, ClaimsPrincipal user, SnapshotCache cache, ExposureBuffer buffer, TimeProvider clock,
        IOptions<RolloutOptions> options, CancellationToken ct)
    {
        if (body.Exposures is null || body.Exposures.Count > options.Value.MaxExposuresPerRequest)
        {
            return TypedResults.BadRequest($"Send between 1 and {options.Value.MaxExposuresPerRequest} exposures per request.");
        }

        var environment = Environment(user);
        var snapshot = await cache.GetAsync(environment, ct);
        var now = clock.GetUtcNow();
        var valid = new List<Exposure>(body.Exposures.Count);
        foreach (var e in body.Exposures)
        {
            // Unknown flags or variants, and timestamps from a badly set device clock, would poison the counts.
            var at = e.At ?? now;
            if (snapshot.Flags.TryGet(e.Flag ?? string.Empty, out var flag)
                && flag.VariantValues.ContainsKey(e.Variant ?? string.Empty)
                && at <= now.AddMinutes(5) && at >= now.AddDays(-2))
            {
                valid.Add(new Exposure(environment, e.Flag!, e.Variant!, at));
            }
        }

        var accepted = buffer.Offer(valid);
        return TypedResults.Accepted((string?)null, new ExposureReceipt(accepted, valid.Count - accepted, body.Exposures.Count - valid.Count));
    }

    private static string Environment(ClaimsPrincipal user) =>
        user.SdkEnvironment() ?? throw new ForbiddenEnvironmentException("(none)");
}
