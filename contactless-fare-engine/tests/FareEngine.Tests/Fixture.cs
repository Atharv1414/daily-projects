using System.Globalization;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using FareEngine.Api.Auth;
using FareEngine.Application.Persistence;
using FareEngine.Application.Rating;
using FareEngine.Application.Settlement;
using FareEngine.Application.Taps;
using FareEngine.Domain;
using FareEngine.Simulator;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

namespace FareEngine.Tests;

/// <summary>The real API over a throwaway SQLite file, with a clock the test controls and no background worker.</summary>
public sealed class FareApp : WebApplicationFactory<Program>
{
    // Invented for these tests only; the host never leaves this process.
    private const string ReaderSecret = "reader-secret-for-tests";
    private readonly string _path = Path.Combine(Path.GetTempPath(), $"fare-test-{Guid.NewGuid():N}.db");

    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { Converters = { new JsonStringEnumConverter() } };

    public SimulatedClock Clock { get; } = new(Make.On(1, "12:00"));

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        ArgumentNullException.ThrowIfNull(builder);
        builder.UseSetting("ConnectionStrings:Fares", $"Data Source={_path}");
        builder.UseSetting("Auth:Readers:gate-1", ReaderSecret);
        builder.UseSetting("Auth:Staff:Asha:KeySha256", Hash("agent-key"));
        builder.UseSetting("Auth:Staff:Asha:Roles:0", "agent");
        builder.UseSetting("Auth:Staff:Finance:KeySha256", Hash("finance-key"));
        builder.UseSetting("Auth:Staff:Finance:Roles:0", "finance");
        builder.UseSetting("Logging:LogLevel:Default", "None");
        builder.ConfigureTestServices(services =>
        {
            services.AddSingleton<TimeProvider>(Clock);
            services.Remove(services.Single(s => s.ServiceType == typeof(IHostedService) && s.ImplementationType == typeof(RatingWorker)));
        });
    }

    public HttpClient Staff(string key)
    {
        var client = CreateClient();
        client.DefaultRequestHeaders.Add(StaffKeyHandler.Header, key);
        return client;
    }

    public async Task<HttpResponseMessage> SendTapsAsync(
        object batch, string reader = "gate-1", string secret = ReaderSecret, DateTimeOffset? signedAt = null, string? tamper = null)
    {
        var body = JsonSerializer.SerializeToUtf8Bytes(batch, Json);
        var timestamp = (signedAt ?? Clock.GetUtcNow()).ToUnixTimeSeconds().ToString(CultureInfo.InvariantCulture);
        var signature = ReaderSignature.Sign(secret, reader, timestamp, body);
        using var request = new HttpRequestMessage(HttpMethod.Post, "/v1/taps");
        request.Content = new ByteArrayContent(tamper is null ? body : Encoding.UTF8.GetBytes(tamper));
        request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        request.Headers.Add(ReaderSignature.ReaderHeader, reader);
        request.Headers.Add(ReaderSignature.TimestampHeader, timestamp);
        request.Headers.Add(ReaderSignature.SignatureHeader, signature);
        return await CreateClient().SendAsync(request);
    }

    public async Task<IReadOnlyList<TapResult>> IngestAsync(params Tap[] taps)
    {
        await using var scope = Services.CreateAsyncScope();
        return await scope.ServiceProvider.GetRequiredService<TapIngestion>().IngestAsync(
            [.. taps.Select(t => new IncomingTap(t.Id, t.CardToken, t.PlaceId, t.Kind, t.OccurredAt))], "test");
    }

    public Task<DrainResult> DrainAsync() => Services.GetRequiredService<RatingProcessor>().DrainAsync();

    public async Task<SettlementSummary> SettleAsync(DateOnly date)
    {
        await using var scope = Services.CreateAsyncScope();
        return await scope.ServiceProvider.GetRequiredService<SettlementService>().SettleAsync(date);
    }

    public async Task<T> DbAsync<T>(Func<FareDbContext, Task<T>> query)
    {
        ArgumentNullException.ThrowIfNull(query);
        await using var scope = Services.CreateAsyncScope();
        return await query(scope.ServiceProvider.GetRequiredService<FareDbContext>());
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        SqliteConnection.ClearAllPools();
        foreach (var suffix in new[] { "", "-wal", "-shm" })
        {
            File.Delete(_path + suffix);
        }
    }

    private static string Hash(string key) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(key)));
}
