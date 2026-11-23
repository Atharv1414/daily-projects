using System.ComponentModel.DataAnnotations;

namespace StockReservation.Application.Common;

/// <summary>Reservation behaviour, bound from the <c>Reservations</c> configuration section.</summary>
public sealed class ReservationOptions
{
    public const string SectionName = "Reservations";

    [Range(1, 1440)]
    public int DefaultHoldMinutes { get; set; } = 30;

    [Range(1, 1440)]
    public int MaxHoldMinutes { get; set; } = 240;

    [Range(1, 200)]
    public int MaxLinesPerReservation { get; set; } = 50;

    [Range(1, 20)]
    public int MaxConcurrencyRetries { get; set; } = 8;
}

/// <summary>Background worker settings, bound from the <c>Workers</c> configuration section.</summary>
public sealed class WorkerOptions
{
    public const string SectionName = "Workers";

    public bool Enabled { get; set; } = true;

    [Range(1, 3600)]
    public int ExpirySweepSeconds { get; set; } = 15;

    [Range(1, 3600)]
    public int OutboxPollSeconds { get; set; } = 2;

    [Range(1, 1000)]
    public int BatchSize { get; set; } = 100;

    [Range(1, 50)]
    public int OutboxMaxAttempts { get; set; } = 6;

    [Range(1, 3600)]
    public int OutboxBaseRetrySeconds { get; set; } = 5;
}
