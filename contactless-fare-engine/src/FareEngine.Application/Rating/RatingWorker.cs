using FareEngine.Application.Persistence;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace FareEngine.Application.Rating;

public sealed record DrainResult(int Rated, int Posted, int Failed);

/// <summary>Works through due jobs. Separate from the background service so tests and tools can call it directly.</summary>
public sealed partial class RatingProcessor(
    IServiceScopeFactory scopes,
    TimeProvider clock,
    IOptions<FareOptions> options,
    ILogger<RatingProcessor> logger)
{
    private const int PageSize = 200;
    private readonly FareOptions _options = options.Value;

    public async Task<DrainResult> DrainAsync(CancellationToken ct = default)
    {
        var (rated, posted, failed) = (0, 0, 0);
        while (true)
        {
            List<RatingJob> due;
            await using (var scope = scopes.CreateAsyncScope())
            {
                due = await scope.ServiceProvider.GetRequiredService<RatingJobs>()
                    .DueAsync(clock.GetUtcNow(), PageSize, ct);
            }

            if (due.Count == 0)
            {
                return new DrainResult(rated, posted, failed);
            }

            await Parallel.ForEachAsync(
                due,
                new ParallelOptions { MaxDegreeOfParallelism = _options.RatingConcurrency, CancellationToken = ct },
                async (job, token) =>
                {
                    await using var scope = scopes.CreateAsyncScope();
                    var rater = scope.ServiceProvider.GetRequiredService<WeekRater>();
                    try
                    {
                        Interlocked.Add(ref posted, await rater.RateAsync(job, token));
                        Interlocked.Increment(ref rated);
                    }
                    catch (Exception e) when (e is not OperationCanceledException)
                    {
                        Interlocked.Increment(ref failed);
                        LogFailure(logger, e, job.CardToken, job.WeekStart, job.Attempts + 1);
                        await using var retry = scopes.CreateAsyncScope();
                        await retry.ServiceProvider.GetRequiredService<WeekRater>()
                            .FailAsync(job, e, _options.MaxRatingAttempts, token);
                    }
                });
        }
    }

    [LoggerMessage(Level = LogLevel.Error, Message = "Rating {Card} week {Week} failed on attempt {Attempt}")]
    private static partial void LogFailure(ILogger logger, Exception error, string card, DateOnly week, int attempt);
}

public sealed partial class RatingWorker(
    RatingProcessor processor,
    RatingSignal signal,
    IOptions<FareOptions> options,
    ILogger<RatingWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var result = await processor.DrainAsync(stoppingToken);
                if (result.Rated + result.Failed > 0)
                {
                    LogDrained(logger, result.Rated, result.Posted, result.Failed);
                }

                await signal.WaitAsync(TimeSpan.FromSeconds(options.Value.PollSeconds), stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception e)
            {
                // The database being briefly unavailable must not stop the worker for good.
                LogDrainFailed(logger, e);
                await Task.Delay(TimeSpan.FromSeconds(options.Value.PollSeconds), stoppingToken)
                    .ConfigureAwait(ConfigureAwaitOptions.SuppressThrowing);
            }
        }
    }

    [LoggerMessage(Level = LogLevel.Information, Message = "Rated {Rated} weeks, posted {Posted} entries, {Failed} failed")]
    private static partial void LogDrained(ILogger logger, int rated, int posted, int failed);

    [LoggerMessage(Level = LogLevel.Error, Message = "Could not drain the rating queue")]
    private static partial void LogDrainFailed(ILogger logger, Exception error);
}
