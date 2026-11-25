using System.Net;
using System.Net.Http.Json;
using FareEngine.Api.Endpoints;
using FareEngine.Application.Taps;
using FareEngine.Domain;

namespace FareEngine.Tests;

public sealed class ApiTests : IDisposable
{
    private readonly FareApp _app = new();

    public void Dispose() => _app.Dispose();

    private static object Batch(params Tap[] taps) =>
        new { Taps = taps.Select(t => new { t.Id, t.CardToken, t.PlaceId, t.Kind, t.OccurredAt }) };

    [Fact]
    public async Task SignedBatch_IsAccepted()
    {
        var response = await _app.SendTapsAsync(Batch(Make.Bus(Make.On(0, "10:00"))));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(1, (await response.Content.ReadFromJsonAsync<TapBatchResult>(FareApp.Json))!.Accepted);
    }

    [Fact]
    public async Task WrongSecretUnknownReaderOldOrChangedBatch_IsRefused()
    {
        var batch = Batch(Make.Bus(Make.On(0, "10:00")));
        HttpResponseMessage[] refused =
        [
            await _app.SendTapsAsync(batch, secret: "wrong"),
            await _app.SendTapsAsync(batch, reader: "gate-99"),
            await _app.SendTapsAsync(batch, reader: "gate-99", secret: "unknown"), // the dummy secret opens nothing
            await _app.SendTapsAsync(batch, signedAt: Make.On(1, "11:54")),
            await _app.SendTapsAsync(batch, tamper: "{\"taps\":[]}"),
            await _app.CreateClient().PostAsJsonAsync("/v1/taps", batch),
        ];
        Assert.All(refused, r => Assert.Equal(HttpStatusCode.Unauthorized, r.StatusCode));
    }

    [Fact]
    public async Task EmptyOrOversizedBatch_IsAClearError()
    {
        Assert.Equal(HttpStatusCode.BadRequest, (await _app.SendTapsAsync(new { })).StatusCode);
        var many = Enumerable.Range(0, 501).Select(i => Make.Bus(Make.On(0, "10:00").AddSeconds(i))).ToArray();
        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, (await _app.SendTapsAsync(Batch(many))).StatusCode);
    }

    [Fact]
    public async Task Statement_ExplainsEachCharge()
    {
        await _app.IngestAsync(Make.Trip("ABBEY", "QUAYSIDE", 0, "08:00", "08:40"));
        var view = await _app.Staff("agent-key")
            .GetFromJsonAsync<StatementView>($"/v1/cards/{Make.Card}/weeks/2026-11-02", FareApp.Json);
        var journey = Assert.Single(view!.Journeys);
        Assert.Equal(("Abbey Wharf", "Quayside", "zones 1-3", 455L), (journey.From, journey.To, journey.Zones, journey.ChargedPence));
    }

    [Fact]
    public async Task Statement_NeedsAMonday() =>
        Assert.Equal(
            HttpStatusCode.BadRequest,
            (await _app.Staff("agent-key").GetAsync($"/v1/cards/{Make.Card}/weeks/2026-11-03")).StatusCode);

    [Theory]
    [InlineData(null, HttpStatusCode.Unauthorized)]
    [InlineData("nope", HttpStatusCode.Unauthorized)]
    [InlineData("agent-key", HttpStatusCode.Forbidden)]
    [InlineData("finance-key", HttpStatusCode.OK)]
    public async Task Settlement_IsForFinanceOnly(string? key, HttpStatusCode expected)
    {
        var client = key is null ? _app.CreateClient() : _app.Staff(key);
        Assert.Equal(expected, (await client.PostAsync("/v1/settlements/2026-11-02", null)).StatusCode);
    }

    [Fact]
    public async Task SettlingTooEarly_IsAConflict() =>
        Assert.Equal(
            HttpStatusCode.Conflict,
            (await _app.Staff("finance-key").PostAsync("/v1/settlements/2026-11-03", null)).StatusCode);

    [Fact]
    public async Task Correction_ReplacesTheMaximumFareAndRecordsWhoAndWhy()
    {
        await _app.IngestAsync(Make.In("ABBEY", Make.On(0, "10:00")));
        await _app.DrainAsync();
        var request = new CorrectionRequest(Guid.NewGuid(), "DOCKS", TapKind.Exit, Make.On(0, "10:30"), "Gate left open");
        var response = await _app.Staff("agent-key").PostAsJsonAsync($"/v1/cards/{Make.Card}/corrections", request, FareApp.Json);
        Assert.Equal(TapOutcome.Accepted, (await response.Content.ReadFromJsonAsync<TapResult>(FareApp.Json))!.Outcome);
        await _app.DrainAsync();

        var page = await _app.Staff("agent-key").GetFromJsonAsync<LedgerPage>($"/v1/cards/{Make.Card}/ledger", FareApp.Json);
        Assert.Equal([950L, -720L], page!.Entries.Select(e => e.AmountPence));
        var stored = await _app.DbAsync(db => Task.FromResult(db.Taps.Single(t => t.Id == request.Id)));
        Assert.Equal(("Asha", "Gate left open", TapSource.StaffCorrection), (stored.SubmittedBy, stored.Reason, stored.Source));
    }

    [Fact]
    public async Task Correction_NeedsAReason()
    {
        var request = new CorrectionRequest(Guid.NewGuid(), "DOCKS", TapKind.Exit, Make.On(0, "10:30"), " ");
        var response = await _app.Staff("agent-key").PostAsJsonAsync($"/v1/cards/{Make.Card}/corrections", request, FareApp.Json);
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Ledger_PagesWithoutGapsOrRepeats()
    {
        for (var day = -7; day <= 0; day++)
        {
            await _app.IngestAsync(Make.Bus(Make.On(day, "10:00")));
        }

        await _app.DrainAsync();
        var client = _app.Staff("agent-key");
        var seen = new List<long>();
        long? after = 0;
        while (after is not null)
        {
            var page = await client.GetFromJsonAsync<LedgerPage>($"/v1/cards/{Make.Card}/ledger?after={after}&limit=3", FareApp.Json);
            seen.AddRange(page!.Entries.Select(e => e.Id));
            after = page.NextAfter;
        }

        Assert.Equal(8, seen.Count);
        Assert.Equal(seen.Distinct().Order(), seen);
    }

    [Theory]
    [InlineData("/health")]
    [InlineData("/openapi/v1.json")]
    public async Task PublicPages_Answer(string path) =>
        Assert.Equal(HttpStatusCode.OK, (await _app.CreateClient().GetAsync(path)).StatusCode);
}
