using FareEngine.Application.Persistence;
using FareEngine.Application.Rating;
using FareEngine.Application.Settlement;
using FareEngine.Application.Taps;
using FareEngine.Domain;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace FareEngine.Tests;

public sealed class PipelineTests : IDisposable
{
    private readonly FareApp _app = new();

    public void Dispose() => _app.Dispose();

    private Task<long> Balance() => _app.DbAsync(db => db.Ledger.SumAsync(e => e.AmountPence));

    [Fact]
    public async Task SameBatchTwice_IsStoredOnce()
    {
        var tap = Make.Bus(Make.On(0, "10:00"));
        Assert.Equal(TapOutcome.Accepted, Assert.Single(await _app.IngestAsync(tap)).Outcome);
        Assert.Equal(TapOutcome.Duplicate, Assert.Single(await _app.IngestAsync(tap)).Outcome);
        Assert.Equal(1, await _app.DbAsync(db => db.Taps.CountAsync()));
    }

    [Fact]
    public async Task ReusedTapId_IsAConflictAndKeepsTheOriginal()
    {
        var tap = Make.Bus(Make.On(0, "10:00"));
        await _app.IngestAsync(tap);
        Assert.Equal(TapOutcome.Conflict, Assert.Single(await _app.IngestAsync(tap with { PlaceId = "BUS-14" })).Outcome);
        Assert.Equal("BUS-1", await _app.DbAsync(db => db.Taps.Select(t => t.PlaceId).SingleAsync()));
    }

    [Fact]
    public async Task BadTaps_AreRejectedWithoutLosingTheGoodOnes()
    {
        var results = await _app.IngestAsync(
            Make.Bus(Make.On(0, "10:00")),
            Make.In("NOWHERE", Make.On(0, "10:00")),
            Make.In("BUS-1", Make.On(0, "10:00")),
            Make.Bus(Make.On(3, "10:00")),
            Make.Bus(Make.On(-90, "10:00")));
        Assert.Equal(
            [TapOutcome.Accepted, TapOutcome.Rejected, TapOutcome.Rejected, TapOutcome.Rejected, TapOutcome.Rejected],
            results.Select(r => r.Outcome));
    }

    [Fact]
    public async Task ConcurrentRetries_ChargeOnce()
    {
        var taps = Enumerable.Range(0, 20).Select(i => Make.Bus(Make.On(0, "06:00").AddMinutes(i * 30))).ToArray();
        await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Task.Run(() => _app.IngestAsync(taps))));
        await Task.WhenAll(Enumerable.Range(0, 4).Select(_ => Task.Run(_app.DrainAsync)));
        Assert.Equal(20, await _app.DbAsync(db => db.Taps.CountAsync()));
        Assert.Equal(555, await Balance());
    }

    [Fact]
    public async Task RatingAgain_PostsNothingNew()
    {
        await _app.IngestAsync(Make.Bus(Make.On(0, "10:00")));
        await _app.DrainAsync();
        await _app.IngestAsync(Make.In("ABBEY", Make.On(0, "12:00")), Make.Out("ABBEY", Make.On(0, "12:02")));
        Assert.Equal(0, (await _app.DrainAsync()).Posted);
    }

    [Fact]
    public async Task LateExit_RefundsTheMaximumFareAfterSettlement()
    {
        await _app.IngestAsync(Make.In("ABBEY", Make.On(0, "10:00")));
        await _app.DrainAsync();
        Assert.Equal(950, (await _app.SettleAsync(Make.Monday)).Collected.Pence);

        await _app.IngestAsync(Make.Out("DOCKS", Make.On(0, "10:30")));
        await _app.DrainAsync();
        _app.Clock.Set(Make.On(2, "08:00"));
        var second = await _app.SettleAsync(Make.Monday.AddDays(1));
        Assert.Equal(950 - 230, second.Refunded.Pence);
        Assert.Equal(230, await Balance());
        Assert.Equal(
            [EntryKind.Charge, EntryKind.Adjustment],
            await _app.DbAsync(db => db.Ledger.OrderBy(e => e.Id).Select(e => e.Kind).ToListAsync()));
    }

    [Fact]
    public async Task OpenJourney_IsChargedWhenItExpires()
    {
        await _app.IngestAsync(Make.In("ABBEY", Make.On(1, "11:50")));
        await _app.DrainAsync();
        Assert.Equal(0, await Balance());
        Assert.Equal(0, (await _app.DrainAsync()).Rated); // not due yet
        _app.Clock.Set(Make.On(1, "14:21"));
        await _app.DrainAsync();
        Assert.Equal(950, await Balance());
    }

    [Fact]
    public async Task Settlement_IsIdempotent()
    {
        await _app.IngestAsync(Make.Bus(Make.On(0, "10:00")));
        await _app.DrainAsync();
        var first = await _app.SettleAsync(Make.Monday);
        var second = await _app.SettleAsync(Make.Monday);
        Assert.False(first.AlreadyDone);
        Assert.Equal(first with { AlreadyDone = true }, second);
        Assert.Equal(1, await _app.DbAsync(db => db.SettlementLines.CountAsync()));
    }

    [Fact]
    public async Task ConcurrentSettlements_ProduceOneLine()
    {
        await _app.IngestAsync(Make.Bus(Make.On(0, "10:00")));
        await _app.DrainAsync();
        var runs = await Task.WhenAll(Enumerable.Range(0, 6).Select(_ => Task.Run(() => _app.SettleAsync(Make.Monday))));
        Assert.Single(runs, r => !r.AlreadyDone);
        Assert.Equal(1, await _app.DbAsync(db => db.SettlementLines.CountAsync()));
    }

    [Fact]
    public async Task Settlement_WaitsForTheDayToCloseAndTheQueueToEmpty()
    {
        await Assert.ThrowsAsync<SettlementNotReadyException>(() => _app.SettleAsync(Make.Monday.AddDays(1)));
        await _app.IngestAsync(Make.Bus(Make.On(0, "10:00")));
        var error = await Assert.ThrowsAsync<SettlementNotReadyException>(() => _app.SettleAsync(Make.Monday));
        Assert.Contains("waiting to be rated", error.Message);
    }

    [Fact]
    public async Task Job_RequestedAgainWhileBeingRated_IsNotLost()
    {
        await _app.IngestAsync(Make.Bus(Make.On(0, "10:00")));
        var seen = await _app.DbAsync(db => db.Jobs.AsNoTracking().SingleAsync(j => j.WeekStart == Make.Monday));
        await _app.IngestAsync(Make.Bus(Make.On(0, "15:00")));
        await using (var scope = _app.Services.CreateAsyncScope())
        {
            Assert.Equal(0, await scope.ServiceProvider.GetRequiredService<WeekRater>().RateAsync(seen)); // stale revision
        }

        Assert.True((await _app.DrainAsync()).Rated > 0);
        Assert.Equal(370, await Balance());
    }

    [Fact]
    public async Task FailingJob_BacksOffThenIsParkedAndBlocksSettlement()
    {
        // A place removed from the network after its taps were stored.
        await _app.DbAsync(async db =>
        {
            db.Taps.Add(new TapRecord
            {
                Id = Guid.NewGuid(),
                CardToken = "broken",
                PlaceId = "CLOSED",
                Kind = TapKind.Board,
                OccurredAtMs = Make.On(0, "10:00").ToUnixTimeMilliseconds(),
                SubmittedBy = "test",
            });
            db.Jobs.Add(new RatingJob { CardToken = "broken", WeekStart = Make.Monday, Revision = 1 });
            return await db.SaveChangesAsync();
        });
        for (var i = 0; i < 5; i++)
        {
            Assert.Equal(1, (await _app.DrainAsync()).Failed);
            Assert.Equal(0, (await _app.DrainAsync()).Failed); // waits before trying again
            await Assert.ThrowsAsync<SettlementNotReadyException>(() => _app.SettleAsync(Make.Monday));
            _app.Clock.Set(_app.Clock.GetUtcNow().AddMinutes(2));
        }

        var job = await _app.DbAsync(db => db.Jobs.AsNoTracking().SingleAsync());
        Assert.True(job.Dead);
        Assert.Contains("CLOSED", job.LastError);
        await Assert.ThrowsAsync<SettlementNotReadyException>(() => _app.SettleAsync(Make.Monday));
    }

    [Fact]
    public async Task Simulation_LedgerMatchesACleanRatingAndTheBank()
    {
        var report = await Simulator.Simulation.RunAsync(cards: 40, weeks: 2, seed: 5);
        Assert.Equal(0, report.MismatchedCardWeeks);
        Assert.Equal(0, report.CardDaysOverCap);
        Assert.Equal(report.Charged, report.Collected - report.Refunded);
        Assert.True(report.Adjustments > 0 && report.Duplicates > 0, "the simulation should exercise lateness and retries");
    }
}
