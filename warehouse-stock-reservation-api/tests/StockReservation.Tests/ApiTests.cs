using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace StockReservation.Tests;

/// <summary>Boots the real API against a private shared-cache in-memory SQLite database.</summary>
public sealed class ApiFactory : WebApplicationFactory<Program>
{
    private readonly string _connectionString = $"Data Source=api-{Guid.NewGuid():N};Mode=Memory;Cache=Shared";
    private readonly SqliteConnection _keepAlive;

    public ApiFactory() : this(writesPerMinute: 1_000)
    {
    }

    internal ApiFactory(int writesPerMinute)
    {
        WritesPerMinute = writesPerMinute;
        _keepAlive = new SqliteConnection(_connectionString);
        _keepAlive.Open();
    }

    public int WritesPerMinute { get; }

    public TestClock Clock { get; } = new(DateTimeOffset.UtcNow);

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseSetting("ConnectionStrings:Stock", _connectionString);
        builder.UseSetting("Workers:Enabled", "false");
        builder.UseSetting("Seed:SkusPerWarehouse", "24");
        builder.UseSetting("RateLimits:WritesPerMinute", WritesPerMinute.ToString(System.Globalization.CultureInfo.InvariantCulture));
        builder.UseSetting("RateLimits:AuthPerMinute", "1000");
        builder.UseSetting("Logging:LogLevel:Default", "Warning");
        builder.ConfigureTestServices(services =>
        {
            services.RemoveAll<TimeProvider>();
            services.AddSingleton<TimeProvider>(Clock);
        });
    }

    public async Task<HttpClient> ClientForAsync(string username)
    {
        var client = CreateClient();
        var password = username switch
        {
            "picker.manchester" => "picker-demo-pass",
            "planner.daventry" => "planner-demo-pass",
            _ => "admin-demo-pass",
        };
        var response = await client.PostAsJsonAsync("/auth/token", new { username, password });
        response.EnsureSuccessStatusCode();
        var token = (await response.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("accessToken").GetString();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return client;
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing)
        {
            _keepAlive.Dispose();
        }
    }
}

public sealed class ApiTests(ApiFactory factory) : IClassFixture<ApiFactory>
{
    private const string Planner = "planner.daventry";
    private const string Picker = "picker.manchester";
    private const string Admin = "ops.admin";

    private static HttpRequestMessage ReserveRequest(string key, string sku, int qty, string warehouse = "DIR1")
    {
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/reservations")
        {
            Content = JsonContent.Create(new
            {
                orderReference = "ORD-" + key,
                warehouseCode = warehouse,
                lines = new[] { new { sku, quantity = qty } },
            }),
        };
        request.Headers.Add("Idempotency-Key", key);
        return request;
    }

    private static async Task<JsonElement> JsonAsync(HttpResponseMessage response) =>
        await response.Content.ReadFromJsonAsync<JsonElement>();

    private static async Task<(string Sku, int Available)> PickStockedSkuAsync(HttpClient client, int minAvailable, string warehouse = "DIR1")
    {
        var page = await JsonAsync(await client.GetAsync(new Uri($"/api/stock?warehouse={warehouse}&pageSize=200", UriKind.Relative)));
        var item = page.GetProperty("items").EnumerateArray()
            .First(i => i.GetProperty("available").GetInt32() >= minAvailable);
        return (item.GetProperty("sku").GetString()!, item.GetProperty("available").GetInt32());
    }

    [Fact]
    public async Task Health_IsAnonymous()
    {
        var response = await factory.CreateClient().GetAsync(new Uri("/health", UriKind.Relative));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task OpenApiDocument_IsServed()
    {
        var doc = await JsonAsync(await factory.CreateClient().GetAsync(new Uri("/openapi/v1.json", UriKind.Relative)));
        Assert.True(doc.GetProperty("paths").TryGetProperty("/api/reservations", out _));
    }

    [Fact]
    public async Task Stock_RequiresToken()
    {
        var response = await factory.CreateClient().GetAsync(new Uri("/api/stock", UriKind.Relative));
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Token_WrongPassword_Is401()
    {
        var response = await factory.CreateClient().PostAsJsonAsync("/auth/token", new { username = Admin, password = "nope" });
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Picker_CannotCreateReservations()
    {
        var client = await factory.ClientForAsync(Picker);
        var response = await client.SendAsync(ReserveRequest("picker-key-1", "KIT-00001", 1));
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Planner_CannotAdjustStock()
    {
        var client = await factory.ClientForAsync(Planner);
        var response = await client.PostAsJsonAsync("/api/stock/DIR1/KIT-00001/adjustments", new { delta = -1, reason = "count" });
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Create_ThenReplay_ReturnsSameReservation()
    {
        var client = await factory.ClientForAsync(Planner);
        var (sku, _) = await PickStockedSkuAsync(client, 2);

        var created = await client.SendAsync(ReserveRequest("api-replay-key", sku, 2));
        var replayed = await client.SendAsync(ReserveRequest("api-replay-key", sku, 2));

        Assert.Equal(HttpStatusCode.Created, created.StatusCode);
        Assert.Equal(HttpStatusCode.OK, replayed.StatusCode);
        Assert.Equal("true", replayed.Headers.GetValues("Idempotent-Replayed").Single());
        Assert.Equal((await JsonAsync(created)).GetProperty("id").GetGuid(), (await JsonAsync(replayed)).GetProperty("id").GetGuid());
        Assert.NotNull(created.Headers.Location);
    }

    [Fact]
    public async Task Create_WithoutIdempotencyKey_Is400WithCode()
    {
        var client = await factory.ClientForAsync(Planner);
        var request = ReserveRequest("ignored-key", "KIT-00001", 1);
        request.Headers.Remove("Idempotency-Key");
        var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("idempotency_key.missing", (await JsonAsync(response)).GetProperty("code").GetString());
    }

    [Fact]
    public async Task Create_MoreThanAvailable_Is409Problem()
    {
        var client = await factory.ClientForAsync(Planner);
        var (sku, available) = await PickStockedSkuAsync(client, 1);
        var response = await client.SendAsync(ReserveRequest("too-many-key", sku, available + 1));

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType!.MediaType);
        Assert.Equal("stock.insufficient", (await JsonAsync(response)).GetProperty("code").GetString());
    }

    [Fact]
    public async Task FullLifecycle_PlannerReserves_PickerConfirms_LedgerShowsBoth()
    {
        var planner = await factory.ClientForAsync(Planner);
        var picker = await factory.ClientForAsync(Picker);
        var (sku, _) = await PickStockedSkuAsync(planner, 3);
        var before = await JsonAsync(await planner.GetAsync(new Uri($"/api/stock/DIR1/{sku}", UriKind.Relative)));

        var created = await JsonAsync(await planner.SendAsync(ReserveRequest("lifecycle-key", sku, 3)));
        var id = created.GetProperty("id").GetGuid();
        var confirm = await picker.PostAsync(new Uri($"/api/reservations/{id}/confirm", UriKind.Relative), null);
        Assert.Equal(HttpStatusCode.OK, confirm.StatusCode);
        Assert.Equal("Confirmed", (await JsonAsync(confirm)).GetProperty("status").GetString());

        var after = await JsonAsync(await planner.GetAsync(new Uri($"/api/stock/DIR1/{sku}", UriKind.Relative)));
        Assert.Equal(before.GetProperty("onHand").GetInt32() - 3, after.GetProperty("onHand").GetInt32());

        var movements = await JsonAsync(await planner.GetAsync(new Uri($"/api/stock/DIR1/{sku}/movements", UriKind.Relative)));
        var types = movements.GetProperty("items").EnumerateArray().Select(m => m.GetProperty("type").GetString()).ToList();
        Assert.Contains("Allocate", types);
        Assert.Contains("Reserve", types);

        var again = await picker.PostAsync(new Uri($"/api/reservations/{id}/confirm", UriKind.Relative), null);
        Assert.Equal(HttpStatusCode.UnprocessableEntity, again.StatusCode);
    }

    [Fact]
    public async Task ExpirySweep_ViaOpsEndpoint_ReturnsStock()
    {
        var planner = await factory.ClientForAsync(Planner);
        var admin = await factory.ClientForAsync(Admin);
        var (sku, available) = await PickStockedSkuAsync(planner, 1, "BRS1");
        var created = await JsonAsync(await planner.SendAsync(ReserveRequest("expiry-key-01", sku, 1, "BRS1")));

        factory.Clock.Advance(TimeSpan.FromMinutes(31));
        var sweep = await JsonAsync(await admin.PostAsync(new Uri("/api/ops/expire", UriKind.Relative), null));
        Assert.True(sweep.GetProperty("expired").GetInt32() >= 1);

        var reservation = await JsonAsync(await planner.GetAsync(new Uri($"/api/reservations/{created.GetProperty("id").GetGuid()}", UriKind.Relative)));
        Assert.Equal("Expired", reservation.GetProperty("status").GetString());
        var stock = await JsonAsync(await planner.GetAsync(new Uri($"/api/stock/BRS1/{sku}", UriKind.Relative)));
        Assert.Equal(available, stock.GetProperty("available").GetInt32());

        var reconcile = await JsonAsync(await admin.GetAsync(new Uri("/api/ops/reconcile", UriKind.Relative)));
        Assert.True(reconcile.GetProperty("consistent").GetBoolean());
    }

    [Fact]
    public async Task StockSearch_PaginatesAndFilters()
    {
        var client = await factory.ClientForAsync(Picker);
        var page = await JsonAsync(await client.GetAsync(new Uri("/api/stock?warehouse=MAN1&skuPrefix=KIT&page=1&pageSize=2", UriKind.Relative)));

        Assert.Equal(2, page.GetProperty("items").GetArrayLength());
        Assert.Equal(4, page.GetProperty("totalCount").GetInt32()); // 24 SKUs / 6 categories
        Assert.All(page.GetProperty("items").EnumerateArray(), i => Assert.StartsWith("KIT-", i.GetProperty("sku").GetString(), StringComparison.Ordinal));
    }

    [Fact]
    public async Task Outbox_DispatchPublishesPendingEvents()
    {
        var admin = await factory.ClientForAsync(Admin);
        var receipt = await admin.PostAsJsonAsync("/api/stock/GLA1/PET-00006/receipts", new { quantity = 10, reference = "PO-1" });
        Assert.Equal(HttpStatusCode.OK, receipt.StatusCode);

        var dispatched = await JsonAsync(await admin.PostAsync(new Uri("/api/ops/outbox/dispatch", UriKind.Relative), null));
        Assert.True(dispatched.GetProperty("published").GetInt32() >= 1);
        var stats = await JsonAsync(await admin.GetAsync(new Uri("/api/ops/outbox", UriKind.Relative)));
        Assert.Equal(0, stats.GetProperty("deadLettered").GetInt32());
    }
}

public sealed class RateLimitTests
{
    [Fact]
    public async Task Writes_AreRateLimitedPerUser()
    {
        using var factory = new ApiFactory(writesPerMinute: 3);
        var client = await factory.ClientForAsync("planner.daventry");
        var statuses = new List<HttpStatusCode>();
        for (var i = 0; i < 5; i++)
        {
            var response = await client.PostAsJsonAsync("/api/stock/DIR1/KIT-00001/receipts", new { quantity = 1 });
            statuses.Add(response.StatusCode);
        }

        Assert.Equal(3, statuses.Count(s => s == HttpStatusCode.OK));
        Assert.Equal(2, statuses.Count(s => s == HttpStatusCode.TooManyRequests));
    }
}
