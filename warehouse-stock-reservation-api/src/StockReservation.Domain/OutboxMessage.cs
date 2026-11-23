namespace StockReservation.Domain;

public enum OutboxStatus
{
    Pending,
    Published,
    DeadLettered,
}

/// <summary>
/// An integration event written in the same transaction as the state change that caused it
/// (transactional outbox), then published asynchronously with retries.
/// </summary>
public sealed class OutboxMessage
{
    private OutboxMessage()
    {
        Type = string.Empty;
        Payload = string.Empty;
    }

    public OutboxMessage(string type, string payload, DateTimeOffset occurredAt)
    {
        Id = Guid.NewGuid();
        Type = type;
        Payload = payload;
        OccurredAt = occurredAt;
        NextAttemptAt = occurredAt;
        Status = OutboxStatus.Pending;
    }

    public Guid Id { get; private set; }

    public string Type { get; private set; }

    public string Payload { get; private set; }

    public DateTimeOffset OccurredAt { get; private set; }

    public OutboxStatus Status { get; private set; }

    public int Attempts { get; private set; }

    public DateTimeOffset NextAttemptAt { get; private set; }

    public DateTimeOffset? PublishedAt { get; private set; }

    public string? LastError { get; private set; }

    public void MarkPublished(DateTimeOffset now)
    {
        Attempts++;
        Status = OutboxStatus.Published;
        PublishedAt = now;
        LastError = null;
    }

    /// <summary>Records a failed publish and schedules a retry with capped exponential backoff.</summary>
    public void MarkFailed(string error, DateTimeOffset now, int maxAttempts, TimeSpan baseDelay)
    {
        Attempts++;
        LastError = error.Length > 500 ? error[..500] : error;
        if (Attempts >= maxAttempts)
        {
            Status = OutboxStatus.DeadLettered;
            return;
        }

        var exponent = Math.Min(Attempts - 1, 10);
        NextAttemptAt = now + (baseDelay * Math.Pow(2, exponent));
    }
}
