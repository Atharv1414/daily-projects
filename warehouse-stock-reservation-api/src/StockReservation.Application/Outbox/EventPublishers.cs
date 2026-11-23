using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;
using StockReservation.Domain;

namespace StockReservation.Application.Outbox;

/// <summary>Delivers an outbox message to the outside world (message bus, webhook, ...).</summary>
public interface IEventPublisher
{
    Task PublishAsync(OutboxMessage message, CancellationToken ct);
}

/// <summary>Default publisher: writes events to the structured log (stand-in for a message bus).</summary>
public sealed partial class LoggingEventPublisher(ILogger<LoggingEventPublisher> logger) : IEventPublisher
{
    public Task PublishAsync(OutboxMessage message, CancellationToken ct)
    {
        LogPublished(logger, message.Type, message.Id, message.Payload);
        return Task.CompletedTask;
    }

    [LoggerMessage(Level = LogLevel.Information, Message = "Published {EventType} {MessageId}: {Payload}")]
    private static partial void LogPublished(ILogger logger, string eventType, Guid messageId, string payload);
}

/// <summary>Captures published events in memory; can be told to fail, for tests and demos.</summary>
public sealed class InMemoryEventPublisher : IEventPublisher
{
    private readonly ConcurrentQueue<OutboxMessage> _published = new();

    /// <summary>Message types that should throw on publish (simulates a broker outage for one topic).</summary>
    public ConcurrentDictionary<string, bool> FailingTypes { get; } = new();

    public IReadOnlyCollection<OutboxMessage> Published => _published;

    public Task PublishAsync(OutboxMessage message, CancellationToken ct)
    {
        if (FailingTypes.ContainsKey(message.Type))
        {
            throw new InvalidOperationException($"Broker rejected {message.Type}.");
        }

        _published.Enqueue(message);
        return Task.CompletedTask;
    }
}
