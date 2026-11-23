using System.Security.Claims;
using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using StockReservation.Api;
using StockReservation.Api.Auth;
using StockReservation.Api.Endpoints;
using StockReservation.Application;
using StockReservation.Application.Persistence;
using StockReservation.Application.Seeding;

var builder = WebApplication.CreateBuilder(args);

builder.Logging.AddJsonConsole(o => o.IncludeScopes = true);

var connectionString = builder.Configuration.GetConnectionString("Stock") ?? "Data Source=stock.db";
builder.Services.AddStockReservation(builder.Configuration, connectionString);

builder.Services.AddOptions<JwtOptions>()
    .Bind(builder.Configuration.GetSection(JwtOptions.SectionName))
    .ValidateDataAnnotations()
    .ValidateOnStart();
builder.Services.Configure<UserStoreOptions>(builder.Configuration.GetSection(UserStoreOptions.SectionName));
// Tokens are stamped with wall-clock time, matching the bearer handler's validation clock.
builder.Services.AddSingleton(sp => new TokenService(
    sp.GetRequiredService<IOptions<JwtOptions>>(),
    sp.GetRequiredService<IOptions<UserStoreOptions>>(),
    TimeProvider.System));

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer();
builder.Services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme)
    .Configure<IOptions<JwtOptions>>((bearer, jwt) =>
    {
        bearer.MapInboundClaims = false;
        bearer.TokenValidationParameters = new TokenValidationParameters
        {
            ValidIssuer = jwt.Value.Issuer,
            ValidAudience = jwt.Value.Audience,
            IssuerSigningKey = TokenService.SigningKey(jwt.Value),
            NameClaimType = ClaimTypes.Name,
            RoleClaimType = ClaimTypes.Role,
            ClockSkew = TimeSpan.FromSeconds(30),
        };
    });

builder.Services.AddAuthorizationBuilder()
    .AddPolicy(Policies.CanRead, p => p.RequireRole(Roles.Picker, Roles.Planner, Roles.Admin))
    .AddPolicy(Policies.CanPick, p => p.RequireRole(Roles.Picker, Roles.Admin))
    .AddPolicy(Policies.CanPlan, p => p.RequireRole(Roles.Planner, Roles.Admin))
    .AddPolicy(Policies.CanAdmin, p => p.RequireRole(Roles.Admin));

builder.Services.AddApiRateLimiting(builder.Configuration);
builder.Services.AddProblemDetails();
builder.Services.AddOpenApi();
builder.Services.AddHealthChecks().AddDbContextCheck<StockDbContext>("database");
builder.Services.ConfigureHttpJsonOptions(o => o.SerializerOptions.Converters.Add(new JsonStringEnumConverter()));

var app = builder.Build();

app.UseExceptionHandler();
app.UseStatusCodePages();
app.UseAuthentication();
app.UseAuthorization();
app.UseRateLimiter();

app.MapOpenApi();
app.MapHealthChecks("/health").AllowAnonymous();
app.MapAuthEndpoints();
app.MapStockEndpoints();
app.MapReservationEndpoints();
app.MapOpsEndpoints();

if (app.Configuration.GetValue("Database:MigrateOnStartup", true))
{
    await using var scope = app.Services.CreateAsyncScope();
    var db = scope.ServiceProvider.GetRequiredService<StockDbContext>();
    await db.Database.MigrateAsync();
    if (app.Configuration.GetValue("Seed:Enabled", true))
    {
        await DataSeeder.SeedAsync(
            db,
            app.Configuration.GetValue("Seed:SkusPerWarehouse", 250),
            app.Configuration.GetValue("Seed:RandomSeed", 42),
            TimeProvider.System.GetUtcNow(),
            CancellationToken.None);
    }
}

await app.RunAsync();

/// <summary>Entry point marker so integration tests can use <c>WebApplicationFactory&lt;Program&gt;</c>.</summary>
public partial class Program;
