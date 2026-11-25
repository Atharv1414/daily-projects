using System.Text.Json.Serialization;
using FareEngine.Api;
using FareEngine.Api.Auth;
using FareEngine.Api.Endpoints;
using FareEngine.Application;
using FareEngine.Application.Persistence;
using FareEngine.Application.Rating;
using Microsoft.AspNetCore.Authentication;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddFareEngine(builder.Configuration.GetConnectionString("Fares") ?? "Data Source=fares.db");
builder.Services.AddHostedService<RatingWorker>();
builder.Services.AddOptions<AuthOptions>().BindConfiguration(AuthOptions.Section);
builder.Services.AddSingleton<ReaderSignature>();
builder.Services.AddAuthentication(StaffKeyHandler.SchemeName)
    .AddScheme<AuthenticationSchemeOptions, StaffKeyHandler>(StaffKeyHandler.SchemeName, null);
builder.Services.AddAuthorizationBuilder()
    .AddPolicy(Policies.Agent, p => p.RequireRole("agent", "finance"))
    .AddPolicy(Policies.Finance, p => p.RequireRole("finance"));
builder.Services.ConfigureHttpJsonOptions(o => o.SerializerOptions.Converters.Add(new JsonStringEnumConverter()));
builder.Services.AddProblemDetails();
builder.Services.AddExceptionHandler<ErrorHandler>();
builder.Services.AddHealthChecks().AddDbContextCheck<FareDbContext>();
builder.Services.AddOpenApi();

var app = builder.Build();

await using (var scope = app.Services.CreateAsyncScope())
{
    await scope.ServiceProvider.GetRequiredService<FareDbContext>().Database.MigrateAsync();
}

app.UseExceptionHandler();
app.UseStatusCodePages();
app.UseAuthentication();
app.UseAuthorization();
app.MapOpenApi();
app.MapHealthChecks("/health");
app.MapTaps();
app.MapCards();
app.MapOps();

await app.RunAsync();

/// <summary>Visible to the integration tests.</summary>
public partial class Program;
