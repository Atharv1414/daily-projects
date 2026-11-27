using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Rollout.Api.Auth;
using Rollout.Application;
using Rollout.Application.Exposures;
using Rollout.Domain;

namespace Rollout.Tests;

/// <summary>A clock the test moves by hand.</summary>
public sealed class ManualClock(DateTimeOffset start) : TimeProvider
{
    private DateTimeOffset _now = start;

    public override DateTimeOffset GetUtcNow() => _now;

    public void Advance(TimeSpan by) => _now += by;
}

/// <summary>The real API over a throwaway SQLite file, with a controlled clock and no background writer.</summary>
public sealed class RolloutApp : WebApplicationFactory<Program>
{
    // Invented for these tests only; the host never leaves this process.
    public const string Admin = "test-admin";
    public const string Editor = "test-editor";
    public const string Viewer = "test-viewer";
    public const string SdkProduction = "test-sdk-production";
    public const string SdkStaging = "test-sdk-staging";

    private readonly string _path = Path.Combine(Path.GetTempPath(), $"rollout-test-{Guid.NewGuid():N}.db");

    public RolloutApp(int sdkPerMinute = 10_000)
    {
        SdkPerMinute = sdkPerMinute;
    }

    public int SdkPerMinute { get; }

    public ManualClock Clock { get; } = new(DemoFlags.ReleaseStart.AddDays(5).AddHours(1));

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        ArgumentNullException.ThrowIfNull(builder);
        builder.UseEnvironment("Testing");
        builder.UseSetting("ConnectionStrings:Rollout", $"Data Source={_path}");
        builder.UseSetting("RateLimits:SdkPerMinute", SdkPerMinute.ToString(System.Globalization.CultureInfo.InvariantCulture));
        builder.UseSetting("Logging:LogLevel:Default", "None");
        Key(builder, "admin", Admin, Roles.Admin);
        Key(builder, "editor", Editor, Roles.Editor);
        Key(builder, "viewer", Viewer, Roles.Viewer);
        Key(builder, "tv-production", SdkProduction, Roles.Sdk, "production");
        Key(builder, "tv-staging", SdkStaging, Roles.Sdk, "staging");
        builder.ConfigureTestServices(services =>
        {
            services.AddSingleton<TimeProvider>(Clock);
            services.Remove(services.Single(s => s.ServiceType == typeof(IHostedService) && s.ImplementationType == typeof(ExposureWriter)));
        });
    }

    public HttpClient As(string key)
    {
        var client = CreateClient();
        client.DefaultRequestHeaders.Add(ApiKeyHandler.Header, key);
        return client;
    }

    public async Task SeedAsync() => await Services.SeedDemoAsync(["staging", "production"]);

    public Task<int> FlushExposuresAsync() => Services.GetRequiredService<ExposureFlusher>().DrainAsync();

    public static async Task<HttpResponseMessage> PutFlagAsync(HttpClient client, string env, FlagDefinition flag, long? ifMatch)
    {
        ArgumentNullException.ThrowIfNull(client);
        ArgumentNullException.ThrowIfNull(flag);
        using var request = new HttpRequestMessage(HttpMethod.Put, $"/v1/environments/{env}/flags/{flag.Key}")
        {
            Content = JsonContent.Create(flag, options: FlagJson.Options),
        };
        if (ifMatch is { } version)
        {
            request.Headers.IfMatch.Add(new EntityTagHeaderValue($"\"{version}\""));
        }

        return await client.SendAsync(request);
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

    private static void Key(IWebHostBuilder builder, string name, string key, string role, string? environment = null)
    {
        builder.UseSetting($"Auth:Keys:{name}:KeySha256", Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(key))));
        builder.UseSetting($"Auth:Keys:{name}:Roles:0", role);
        if (environment is not null)
        {
            builder.UseSetting($"Auth:Keys:{name}:Environments:0", environment);
        }
    }
}
