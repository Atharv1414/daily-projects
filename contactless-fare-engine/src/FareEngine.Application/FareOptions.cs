using System.ComponentModel.DataAnnotations;

namespace FareEngine.Application;

public sealed class FareOptions
{
    public const string Section = "Fares";

    /// <summary>Taps older than this are refused: the week is closed for good.</summary>
    [Range(1, 120)]
    public int AcceptTapsForDays { get; set; } = 56;

    /// <summary>How far ahead a reader's clock may run before a tap is refused.</summary>
    [Range(0, 60)]
    public int MaxClockSkewMinutes { get; set; } = 5;

    [Range(1, 1000)]
    public int MaxTapsPerBatch { get; set; } = 500;

    [Range(1, 20)]
    public int MaxRatingAttempts { get; set; } = 5;

    [Range(1, 64)]
    public int RatingConcurrency { get; set; } = 4;

    [Range(1, 60)]
    public int PollSeconds { get; set; } = 5;

    /// <summary>Hours after a service day ends before it may be settled, so most late taps make it in.</summary>
    [Range(0, 72)]
    public int SettlementGraceHours { get; set; } = 3;
}
