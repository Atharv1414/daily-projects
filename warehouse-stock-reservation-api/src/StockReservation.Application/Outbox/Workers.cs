using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using StockReservation.Application.Common;
using StockReservation.Application.Reservations;

namespace StockReservation.Application.Outbox;

/// <summary>Polls the outbox and publishes pending events. Runs as a single instance per database.</summary>
public sealed partial class OutboxPublisherWorker(
    IServiceScopeFactory scopes,
    IOptions<WorkerOptions> options,
    TimeProvider clock,
    ILogger<OutboxPublisherWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(options.Value.OutboxPollSeconds), clock);
        do
        {
            try
            {
                await using var scope = scopes.CreateAsyncScope();
                var dispatcher = scope.ServiceProvider.GetRequiredService<OutboxDispatcher>();
                var summary = await dispatcher.DispatchBatchAsync(stoppingToken);
                if (summary.Published + summary.Failed + summary.DeadLettered > 0)
                {
                    LogBatch(logger, summary.Published, summary.Failed, summary.DeadLettered);
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                // Never let one bad poll kill the worker; the next tick retries.
                LogPollFailed(logger, ex);
            }
        }
        while (await timer.WaitForNextTickAsync(stoppingToken));
    }

    [LoggerMessage(Level = LogLevel.Information, Message = "Outbox batch: {Published} published, {Failed} failed, {Dead} dead-lettered")]
    private static partial void LogBatch(ILogger logger, int published, int failed, int dead);

    [LoggerMessage(Level = LogLevel.Error, Message = "Outbox poll failed")]
    private static partial void LogPollFailed(ILogger logger, Exception ex);
}

/// <summary>Periodically expires reservations whose hold has lapsed, returning their stock.</summary>
public sealed partial class ReservationExpiryWorker(
    IServiceScopeFactory scopes,
    IOptions<WorkerOptions> options,
    TimeProvider clock,
    ILogger<ReservationExpiryWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(options.Value.ExpirySweepSeconds), clock);
        while (await timer.WaitForNextTickAsync(stoppingToken))
        {
            try
            {
                await using var scope = scopes.CreateAsyncScope();
                var service = scope.ServiceProvider.GetRequiredService<ReservationService>();
                await service.ExpireDueAsync(options.Value.BatchSize, stoppingToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                LogSweepFailed(logger, ex);
            }
        }
    }

    [LoggerMessage(Level = LogLevel.Error, Message = "Expiry sweep failed")]
    private static partial void LogSweepFailed(ILogger logger, Exception ex);
}
