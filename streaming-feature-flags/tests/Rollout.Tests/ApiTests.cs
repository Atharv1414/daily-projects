using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Rollout.Api.Endpoints;
using Rollout.Application;
using Rollout.Application.Exposures;
using Rollout.Application.Flags;
using Rollout.Application.Snapshots;
using Rollout.Domain;

namespace Rollout.Tests;

public sealed class ApiTests : IAsyncLifetime, IDisposable
{
    private readonly RolloutApp _app = new();

    public Task InitializeAsync() => _app.SeedAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    public void Dispose() => _app.Dispose();

    private static async Task<T> Read<T>(HttpResponseMessage response) =>
        (await response.Content.ReadFromJsonAsync<T>(FlagJson.Options))!;

    [Theory]
    [InlineData(null, HttpStatusCode.Unauthorized)]
    [InlineData("not-a-real-key", HttpStatusCode.Unauthorized)]
    [InlineData(RolloutApp.SdkProduction, HttpStatusCode.Forbidden)]
    [InlineData(RolloutApp.Viewer, HttpStatusCode.OK)]
    public async Task Admin_endpoints_need_a_person_key(string? key, HttpStatusCode expected)
    {
        using var client = key is null ? _app.CreateClient() : _app.As(key);
        var response = await client.GetAsync("/v1/environments/production/flags");
        Assert.Equal(expected, response.StatusCode);
    }

    [Fact]
    public async Task Editors_change_staging_but_only_admins_change_production()
    {
        using var editor = _app.As(RolloutApp.Editor);
        var flag = FlagDefinition.Boolean("search.voice", false, Serve.Fixed("on"));
        Assert.Equal(HttpStatusCode.Created, (await RolloutApp.PutFlagAsync(editor, "staging", flag, null)).StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, (await RolloutApp.PutFlagAsync(editor, "production", flag, null)).StatusCode);
        using var viewer = _app.As(RolloutApp.Viewer);
        Assert.Equal(HttpStatusCode.Forbidden, (await RolloutApp.PutFlagAsync(viewer, "staging", flag with { Key = "search.other" }, null)).StatusCode);
    }

    [Fact]
    public async Task Anyone_on_call_can_pull_the_kill_switch_in_production()
    {
        using var editor = _app.As(RolloutApp.Editor);
        var off = await editor.PostAsync("/v1/environments/production/flags/player.v2/disable", null);
        Assert.Equal(HttpStatusCode.OK, off.StatusCode);
        Assert.False((await Read<StoredFlag>(off)).Definition.On);
        var on = await editor.PostAsync("/v1/environments/production/flags/player.v2/enable", null);
        Assert.Equal(HttpStatusCode.Forbidden, on.StatusCode);
    }

    [Fact]
    public async Task Updates_need_the_current_version_and_stale_ones_are_refused()
    {
        using var admin = _app.As(RolloutApp.Admin);
        var get = await admin.GetAsync("/v1/environments/production/flags/autoplay.countdown");
        Assert.Equal("\"1\"", get.Headers.ETag!.Tag);
        var flag = (await Read<StoredFlag>(get)).Definition with { Description = "Countdown length test, round 2." };

        var noVersion = await RolloutApp.PutFlagAsync(admin, "production", flag, null);
        Assert.Equal((HttpStatusCode)428, noVersion.StatusCode);

        var ok = await RolloutApp.PutFlagAsync(admin, "production", flag, 1);
        Assert.Equal(HttpStatusCode.OK, ok.StatusCode);
        Assert.Equal("\"2\"", ok.Headers.ETag!.Tag);

        var stale = await RolloutApp.PutFlagAsync(admin, "production", flag with { On = false }, 1);
        Assert.Equal(HttpStatusCode.PreconditionFailed, stale.StatusCode);
        using var problem = JsonDocument.Parse(await stale.Content.ReadAsStringAsync());
        Assert.Equal(2, problem.RootElement.GetProperty("currentVersion").GetInt64());
    }

    [Fact]
    public async Task Concurrent_writers_with_the_same_version_cannot_both_win()
    {
        using var admin = _app.As(RolloutApp.Admin);
        var flag = DemoFlags.DownloadQuality();
        var attempts = await Task.WhenAll(Enumerable.Range(0, 8).Select(i =>
            RolloutApp.PutFlagAsync(admin, "staging", flag with { Description = $"writer {i}" }, 1)));
        Assert.Equal(1, attempts.Count(r => r.StatusCode == HttpStatusCode.OK));
        Assert.Equal(7, attempts.Count(r => r.StatusCode == HttpStatusCode.PreconditionFailed));
        var history = await admin.GetFromJsonAsync<List<AuditEntry>>("/v1/environments/staging/flags/downloads.max-quality/history", FlagJson.Options);
        Assert.Equal([2L, 1L], history!.Select(h => h.Version));
    }

    [Fact]
    public async Task Invalid_definitions_come_back_with_every_error_and_its_path()
    {
        using var admin = _app.As(RolloutApp.Admin);
        var bad = DemoFlags.AutoplayCountdown() with
        {
            Key = "autoplay.v2",
            Rules = [new Rule("broken", "profile.type ==", Serve.Fixed("s99"))],
        };
        var response = await RolloutApp.PutFlagAsync(admin, "staging", bad, null);
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var errors = JsonDocument.Parse(await response.Content.ReadAsStringAsync()).RootElement.GetProperty("errors");
        var paths = errors.EnumerateArray().Select(e => e.GetProperty("path").GetString()).ToList();
        Assert.Equal(["rules[0].condition", "rules[0].serve"], paths);
    }

    [Fact]
    public async Task Snapshot_supports_conditional_polling_and_changes_after_a_write()
    {
        using var tv = _app.As(RolloutApp.SdkProduction);
        var first = await tv.GetAsync("/v1/sdk/snapshot");
        Assert.Equal(HttpStatusCode.OK, first.StatusCode);
        var etag = first.Headers.ETag!.Tag;
        var document = await Read<SnapshotDocument>(first);
        Assert.Equal(6, document.Flags.Count);

        using var poll = new HttpRequestMessage(HttpMethod.Get, "/v1/sdk/snapshot");
        poll.Headers.IfNoneMatch.ParseAdd(etag);
        Assert.Equal(HttpStatusCode.NotModified, (await tv.SendAsync(poll)).StatusCode);

        using var admin = _app.As(RolloutApp.Admin);
        await admin.PostAsync("/v1/environments/production/flags/home.ad-tier-banner/disable", null);
        var after = await tv.GetAsync("/v1/sdk/snapshot");
        Assert.NotEqual(etag, after.Headers.ETag!.Tag);
        var banner = (await Read<SnapshotDocument>(after)).Flags.Single(f => f.Definition.Key == "home.ad-tier-banner");
        Assert.Equal((2L, false), (banner.Version, banner.Definition.On));
    }

    [Fact]
    public async Task Snapshots_are_built_once_per_change_not_once_per_poll()
    {
        using var tv = _app.As(RolloutApp.SdkProduction);
        var cache = (SnapshotCache)_app.Services.GetService(typeof(SnapshotCache))!;
        var before = cache.Builds;
        await Task.WhenAll(Enumerable.Range(0, 50).Select(_ => tv.GetAsync("/v1/sdk/snapshot")));
        Assert.Equal(before + 1, cache.Builds);
    }

    [Fact]
    public async Task An_sdk_key_only_ever_sees_its_own_environment()
    {
        using var admin = _app.As(RolloutApp.Admin);
        await admin.PostAsync("/v1/environments/staging/flags/player.v2/disable", null);
        using var staging = _app.As(RolloutApp.SdkStaging);
        using var production = _app.As(RolloutApp.SdkProduction);
        var s = await Read<SnapshotDocument>(await staging.GetAsync("/v1/sdk/snapshot"));
        var p = await Read<SnapshotDocument>(await production.GetAsync("/v1/sdk/snapshot"));
        Assert.Equal(("staging", "production"), (s.Environment, p.Environment));
        Assert.False(s.Flags.Single(f => f.Definition.Key == "player.v2").Definition.On);
        Assert.True(p.Flags.Single(f => f.Definition.Key == "player.v2").Definition.On);
    }

    [Fact]
    public async Task Server_side_evaluation_explains_each_answer_and_tracks_experiments()
    {
        using var tv = _app.As(RolloutApp.SdkProduction);
        var body = new
        {
            context = new { userId = "user-0001", deviceId = "device-qa-01", householdId = "hh-1", plan = "premium", appVersion = "7.4.1", device = new { platform = "smarttv", year = 2016 } },
        };
        var response = await tv.PostAsJsonAsync("/v1/sdk/evaluate", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var results = doc.RootElement.GetProperty("evaluations").EnumerateArray()
            .ToDictionary(e => e.GetProperty("flagKey").GetString()!, e => (Variant: e.GetProperty("variant").GetString(), Reason: e.GetProperty("reason").GetString()));
        Assert.Equal(("on", "targetMatch"), results["player.v2"]);
        Assert.Equal(("uhd", "ruleMatch"), results["downloads.max-quality"]);
        Assert.Equal("fallthrough", results["autoplay.countdown"].Reason);

        Assert.Equal(2, await _app.FlushExposuresAsync()); // autoplay.countdown and live.low-latency are experiments
    }

    [Fact]
    public async Task Exposures_feed_the_sample_ratio_report_and_junk_is_rejected()
    {
        using var tv = _app.As(RolloutApp.SdkProduction);
        var now = _app.Clock.GetUtcNow();
        var batch = Enumerable.Range(0, 900).Select(i => new ExposureInput("live.low-latency", i % 3 == 0 ? "off" : "on", now.AddMinutes(-i % 50)))
            .Concat([new ExposureInput("no.such.flag", "on"), new ExposureInput("live.low-latency", "purple"), new ExposureInput("live.low-latency", "on", now.AddDays(3))])
            .ToList();
        var receipt = await Read<ExposureReceipt>(await tv.PostAsJsonAsync("/v1/sdk/exposures", new ExposureBatch(batch)));
        Assert.Equal(new ExposureReceipt(900, 0, 3), receipt);
        Assert.Equal(900, await _app.FlushExposuresAsync());

        using var viewer = _app.As(RolloutApp.Viewer);
        var report = await viewer.GetFromJsonAsync<ExperimentReport>("/v1/environments/production/flags/live.low-latency/experiment", FlagJson.Options);
        Assert.Equal([600L, 300L], report!.Variants.Select(v => v.Exposures));
        Assert.True(report.SampleRatio.Mismatch);
        Assert.StartsWith("Too few exposures", report.Verdict, StringComparison.Ordinal);

        var notExperiment = await viewer.GetAsync("/v1/environments/production/flags/kids.pin-lock/experiment");
        Assert.Equal(HttpStatusCode.Conflict, notExperiment.StatusCode);
    }

    [Fact]
    public async Task Repeated_flushes_add_to_the_same_hourly_row()
    {
        using var tv = _app.As(RolloutApp.SdkProduction);
        for (var round = 0; round < 3; round++)
        {
            var batch = Enumerable.Range(0, 10).Select(_ => new ExposureInput("autoplay.countdown", "s5")).ToList();
            await tv.PostAsJsonAsync("/v1/sdk/exposures", new ExposureBatch(batch));
            await _app.FlushExposuresAsync();
        }

        using var viewer = _app.As(RolloutApp.Viewer);
        var report = await viewer.GetFromJsonAsync<ExperimentReport>("/v1/environments/production/flags/autoplay.countdown/experiment", FlagJson.Options);
        Assert.Equal(30, report!.Variants.Single(v => v.Variant == "s5").Exposures);
    }

    [Fact]
    public async Task A_prerequisite_cannot_be_archived_while_something_depends_on_it()
    {
        using var admin = _app.As(RolloutApp.Admin);
        using var blocked = new HttpRequestMessage(HttpMethod.Delete, "/v1/environments/staging/flags/kids.pin-lock");
        blocked.Headers.IfMatch.ParseAdd("\"1\"");
        var response = await admin.SendAsync(blocked);
        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Contains("live.low-latency", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);

        using var archive = new HttpRequestMessage(HttpMethod.Delete, "/v1/environments/staging/flags/live.low-latency");
        archive.Headers.IfMatch.ParseAdd("\"1\"");
        Assert.Equal(HttpStatusCode.NoContent, (await admin.SendAsync(archive)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await admin.GetAsync("/v1/environments/staging/flags/live.low-latency")).StatusCode);
    }

    [Fact]
    public async Task Promotion_copies_targeting_but_never_switches_production_on()
    {
        using var admin = _app.As(RolloutApp.Admin);
        var staged = DemoFlags.AdTierBanner() with { Rules = [new Rule("lapsed-gb-ie", "country in [\"GB\", \"IE\"] and status == \"lapsed\"", Serve.Fixed("on"))] };
        await RolloutApp.PutFlagAsync(admin, "staging", staged, 1);
        await admin.PostAsync("/v1/environments/production/flags/home.ad-tier-banner/disable", null);

        var promoted = await admin.PostAsync("/v1/environments/staging/flags/home.ad-tier-banner/promote?to=production", null);
        Assert.Equal(HttpStatusCode.OK, promoted.StatusCode);
        var flag = await Read<StoredFlag>(promoted);
        Assert.Equal(("lapsed-gb-ie", false, 3L), (flag.Definition.RuleList.Single().Id, flag.Definition.On, flag.Version));

        using var editor = _app.As(RolloutApp.Editor);
        Assert.Equal(HttpStatusCode.Forbidden, (await editor.PostAsync("/v1/environments/staging/flags/home.ad-tier-banner/promote?to=production", null)).StatusCode);
    }

    [Fact]
    public async Task Listing_pages_through_flags_and_filters_by_tag()
    {
        using var viewer = _app.As(RolloutApp.Viewer);
        var first = await viewer.GetFromJsonAsync<Page<FlagSummary>>("/v1/environments/production/flags?limit=4", FlagJson.Options);
        Assert.Equal(4, first!.Items.Count);
        var second = await viewer.GetFromJsonAsync<Page<FlagSummary>>($"/v1/environments/production/flags?limit=4&cursor={first.NextCursor}", FlagJson.Options);
        Assert.Equal(2, second!.Items.Count);
        Assert.Null(second.NextCursor);
        Assert.Empty(first.Items.Select(i => i.Key).Intersect(second.Items.Select(i => i.Key)));

        var experiments = await viewer.GetFromJsonAsync<Page<FlagSummary>>("/v1/environments/production/flags?tag=experiment", FlagJson.Options);
        Assert.Equal(["autoplay.countdown", "live.low-latency"], experiments!.Items.Select(i => i.Key));
        Assert.Equal(HttpStatusCode.NotFound, (await viewer.GetAsync("/v1/environments/prod/flags")).StatusCode);
    }

    [Fact]
    public async Task History_records_who_did_what()
    {
        using var editor = _app.As(RolloutApp.Editor);
        await editor.PostAsync("/v1/environments/production/flags/live.low-latency/disable", null);
        var history = await editor.GetFromJsonAsync<List<AuditEntry>>("/v1/environments/production/flags/live.low-latency/history", FlagJson.Options);
        Assert.Equal(("editor", "disable", "Turned off (kill switch)."), (history![0].Actor, history[0].Action, history[0].Changes.Single()));
        Assert.Equal(("seed", "create"), (history[1].Actor, history[1].Action));
    }

    [Fact]
    public async Task Sdk_traffic_is_rate_limited_per_key()
    {
        using var app = new RolloutApp(sdkPerMinute: 3);
        await app.SeedAsync();
        using var tv = app.As(RolloutApp.SdkProduction);
        var codes = new List<HttpStatusCode>();
        for (var i = 0; i < 5; i++)
        {
            codes.Add((await tv.GetAsync("/v1/sdk/snapshot")).StatusCode);
        }

        Assert.Equal([HttpStatusCode.OK, HttpStatusCode.OK, HttpStatusCode.OK, HttpStatusCode.TooManyRequests, HttpStatusCode.TooManyRequests], codes);
        using var other = app.As(RolloutApp.SdkStaging);
        Assert.Equal(HttpStatusCode.OK, (await other.GetAsync("/v1/sdk/snapshot")).StatusCode);
    }
}
