using System.Text.Json.Serialization;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Authentication;
using Microsoft.EntityFrameworkCore;
using Rollout.Api;
using Rollout.Api.Auth;
using Rollout.Api.Endpoints;
using Rollout.Application;
using Rollout.Application.Exposures;
using Rollout.Application.Persistence;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRollout(builder.Configuration.GetConnectionString("Rollout") ?? "Data Source=rollout.db");
builder.Services.AddHostedService<ExposureWriter>();
builder.Services.AddOptions<AuthOptions>().BindConfiguration(AuthOptions.Section);
builder.Services.AddAuthentication(ApiKeyHandler.SchemeName)
    .AddScheme<AuthenticationSchemeOptions, ApiKeyHandler>(ApiKeyHandler.SchemeName, null);
builder.Services.AddAuthorizationBuilder()
    .AddPolicy(Policies.Read, p => p.RequireRole(Roles.Viewer, Roles.Editor, Roles.Admin))
    .AddPolicy(Policies.Sdk, p => p.RequireRole(Roles.Sdk).RequireAssertion(c => c.User.SdkEnvironment() is not null));

var perMinute = builder.Configuration.GetValue("RateLimits:SdkPerMinute", 600);
builder.Services.AddRateLimiter(o =>
{
    o.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    // One bucket per key: a misbehaving app build cannot starve every other client.
    o.AddPolicy(SdkEndpoints.RateLimitPolicy, http => RateLimitPartition.GetFixedWindowLimiter(
        http.User.Identity?.Name ?? http.Connection.RemoteIpAddress?.ToString() ?? "anonymous",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = perMinute, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
});
builder.Services.ConfigureHttpJsonOptions(o =>
{
    o.SerializerOptions.Converters.Add(new JsonStringEnumConverter(System.Text.Json.JsonNamingPolicy.CamelCase));
    o.SerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;
});
builder.Services.AddProblemDetails();
builder.Services.AddExceptionHandler<ErrorHandler>();
builder.Services.AddHealthChecks().AddDbContextCheck<RolloutDbContext>();
builder.Services.AddOpenApi();

var app = builder.Build();

await using (var scope = app.Services.CreateAsyncScope())
{
    await scope.ServiceProvider.GetRequiredService<RolloutDbContext>().Database.MigrateAsync();
}

if (app.Configuration.GetValue("Rollout:SeedDemo", false))
{
    await app.Services.SeedDemoAsync(["development", "staging", "production"]);
}

app.UseExceptionHandler();
app.UseStatusCodePages();
app.UseAuthentication();
app.UseAuthorization();
app.UseRateLimiter();
app.MapOpenApi();
app.MapHealthChecks("/health");
app.MapAdmin();
app.MapSdk();

await app.RunAsync();

/// <summary>Visible to the integration tests.</summary>
public partial class Program;
