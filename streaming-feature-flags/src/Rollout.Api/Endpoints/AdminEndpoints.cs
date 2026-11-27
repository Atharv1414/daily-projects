using System.Security.Claims;
using Microsoft.AspNetCore.Http.HttpResults;
using Rollout.Api.Auth;
using Rollout.Application.Exposures;
using Rollout.Application.Flags;
using Rollout.Domain;

namespace Rollout.Api.Endpoints;

/// <summary>Endpoints for people and release tooling: author, toggle, promote and audit flags.</summary>
public static class AdminEndpoints
{
    public static IEndpointRouteBuilder MapAdmin(this IEndpointRouteBuilder app)
    {
        var flags = app.MapGroup("/v1/environments/{env}/flags")
            .RequireAuthorization(Policies.Read)
            .WithTags("Flags");

        flags.MapGet("/", ListAsync).WithSummary("List flags, filtered by key text or tag, with keyset pagination.");
        flags.MapGet("/{key}", GetAsync).WithSummary("Read a flag. The ETag is its version; send it back as If-Match.");
        flags.MapPut("/{key}", PutAsync).WithSummary("Create (no If-Match) or replace (If-Match: \"version\") a flag.");
        flags.MapPost("/{key}/enable", (string env, string key, ClaimsPrincipal user, FlagStore store, CancellationToken ct) =>
            SetOnAsync(env, key, true, user, store, ct)).WithSummary("Turn the flag on.");
        flags.MapPost("/{key}/disable", (string env, string key, ClaimsPrincipal user, FlagStore store, CancellationToken ct) =>
            SetOnAsync(env, key, false, user, store, ct)).WithSummary("Kill switch: serve the off variant to everyone. Needs no version.");
        flags.MapDelete("/{key}", ArchiveAsync).WithSummary("Archive a flag (If-Match required). SDKs stop receiving it.");
        flags.MapPost("/{key}/promote", PromoteAsync).WithSummary("Copy targeting to another environment, keeping its on/off state.");
        flags.MapGet("/{key}/history", HistoryAsync).WithSummary("Audit trail, newest first.");
        flags.MapGet("/{key}/experiment", ExperimentAsync).WithSummary("Exposures per variant and a sample-ratio-mismatch check.");
        return app;
    }

    private static Task<Page<FlagSummary>> ListAsync(
        string env, string? search, string? tag, string? cursor, int? limit, ClaimsPrincipal user, FlagStore store, CancellationToken ct)
    {
        RequireRead(user, env);
        return store.ListAsync(env, search, tag, cursor, limit ?? 50, ct);
    }

    private static async Task<Ok<StoredFlag>> GetAsync(string env, string key, ClaimsPrincipal user, FlagStore store, HttpResponse response, CancellationToken ct)
    {
        RequireRead(user, env);
        var flag = await store.GetAsync(env, key, ct);
        response.Headers.ETag = Http.VersionTag(flag.Version);
        return TypedResults.Ok(flag);
    }

    private static async Task<Results<Ok<StoredFlag>, Created<StoredFlag>, ForbidHttpResult, BadRequest<string>>> PutAsync(
        string env, string key, FlagDefinition definition, ClaimsPrincipal user, FlagStore store, HttpRequest request, HttpResponse response, CancellationToken ct)
    {
        if (!user.MayWrite(env))
        {
            return TypedResults.Forbid();
        }

        if (definition.Key != key)
        {
            return TypedResults.BadRequest($"The body is for '{definition.Key}' but the URL says '{key}'.");
        }

        var expected = Http.IfMatchVersion(request);
        var saved = await store.SaveAsync(env, definition, expected, Actor(user), ct);
        response.Headers.ETag = Http.VersionTag(saved.Version);
        return saved.Version == 1 || expected is null
            ? TypedResults.Created($"/v1/environments/{env}/flags/{key}", saved)
            : TypedResults.Ok(saved);
    }

    private static async Task<Results<Ok<StoredFlag>, ForbidHttpResult>> SetOnAsync(
        string env, string key, bool on, ClaimsPrincipal user, FlagStore store, CancellationToken ct)
    {
        // Turning a flag off is allowed for editors even in production: anyone on call must be able to stop a bad release.
        var allowed = on ? user.MayWrite(env) : user.MayUse(env) && (user.IsInRole(Roles.Editor) || user.IsInRole(Roles.Admin));
        if (!allowed)
        {
            return TypedResults.Forbid();
        }

        return TypedResults.Ok(await store.SetOnAsync(env, key, on, Actor(user), ct));
    }

    private static async Task<Results<NoContent, ForbidHttpResult, StatusCodeHttpResult>> ArchiveAsync(
        string env, string key, ClaimsPrincipal user, FlagStore store, HttpRequest request, CancellationToken ct)
    {
        if (!user.MayWrite(env))
        {
            return TypedResults.Forbid();
        }

        if (Http.IfMatchVersion(request) is not { } expected)
        {
            return TypedResults.StatusCode(StatusCodes.Status428PreconditionRequired);
        }

        await store.ArchiveAsync(env, key, expected, Actor(user), ct);
        return TypedResults.NoContent();
    }

    private static async Task<Results<Ok<StoredFlag>, ForbidHttpResult>> PromoteAsync(
        string env, string key, string to, ClaimsPrincipal user, FlagStore store, CancellationToken ct)
    {
        if (!user.MayUse(env) || !user.MayWrite(to))
        {
            return TypedResults.Forbid();
        }

        return TypedResults.Ok(await store.PromoteAsync(env, to, key, Actor(user), ct));
    }

    private static Task<IReadOnlyList<AuditEntry>> HistoryAsync(
        string env, string key, int? limit, ClaimsPrincipal user, FlagStore store, CancellationToken ct)
    {
        RequireRead(user, env);
        return store.HistoryAsync(env, key, limit ?? 50, ct);
    }

    private static Task<ExperimentReport> ExperimentAsync(
        string env, string key, DateTimeOffset? since, ClaimsPrincipal user, ExperimentReports reports, CancellationToken ct)
    {
        RequireRead(user, env);
        return reports.ForFlagAsync(env, key, since, ct);
    }

    private static void RequireRead(ClaimsPrincipal user, string env)
    {
        if (!user.MayUse(env))
        {
            throw new ForbiddenEnvironmentException(env);
        }
    }

    private static string Actor(ClaimsPrincipal user) => user.Identity?.Name ?? "unknown";
}

/// <summary>The key is valid but not for this environment.</summary>
public sealed class ForbiddenEnvironmentException(string environment)
    : Exception($"This key cannot use the '{environment}' environment.");
