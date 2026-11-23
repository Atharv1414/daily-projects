using System.Globalization;
using System.Security.Claims;
using System.Threading.RateLimiting;

namespace StockReservation.Api;

public sealed class RateLimitOptions
{
    public const string SectionName = "RateLimits";

    public int WritesPerMinute { get; set; } = 120;

    public int AuthPerMinute { get; set; } = 10;
}

/// <summary>Per-user token bucket for writes and per-IP fixed window for the token endpoint.</summary>
public static class RateLimitPolicies
{
    public const string Writes = "writes";
    public const string Auth = "auth";

    public static IServiceCollection AddApiRateLimiting(this IServiceCollection services, IConfiguration config)
    {
        var opts = config.GetSection(RateLimitOptions.SectionName).Get<RateLimitOptions>() ?? new RateLimitOptions();
        services.AddRateLimiter(limiter =>
        {
            limiter.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
            limiter.OnRejected = (context, _) =>
            {
                if (context.Lease.TryGetMetadata(MetadataName.RetryAfter, out var retryAfter))
                {
                    context.HttpContext.Response.Headers.RetryAfter =
                        ((int)Math.Ceiling(retryAfter.TotalSeconds)).ToString(CultureInfo.InvariantCulture);
                }

                return ValueTask.CompletedTask;
            };

            limiter.AddPolicy(Writes, http => RateLimitPartition.GetTokenBucketLimiter(
                http.User.FindFirstValue(ClaimTypes.Name) ?? http.Connection.RemoteIpAddress?.ToString() ?? "anonymous",
                _ => new TokenBucketRateLimiterOptions
                {
                    TokenLimit = opts.WritesPerMinute,
                    TokensPerPeriod = opts.WritesPerMinute,
                    ReplenishmentPeriod = TimeSpan.FromMinutes(1),
                    QueueLimit = 0,
                    AutoReplenishment = true,
                }));

            limiter.AddPolicy(Auth, http => RateLimitPartition.GetFixedWindowLimiter(
                http.Connection.RemoteIpAddress?.ToString() ?? "unknown",
                _ => new FixedWindowRateLimiterOptions
                {
                    PermitLimit = opts.AuthPerMinute,
                    Window = TimeSpan.FromMinutes(1),
                    QueueLimit = 0,
                }));
        });
        return services;
    }
}
