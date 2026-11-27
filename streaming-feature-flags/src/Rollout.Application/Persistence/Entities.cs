namespace Rollout.Application.Persistence;

/// <summary>
/// The current definition of a flag in one environment. The definition is stored as JSON because it is
/// always read and written whole, and its shape evolves faster than a relational schema would like.
/// </summary>
public sealed class FlagRecord
{
    public long Id { get; set; }

    public required string Environment { get; set; }

    public required string Key { get; set; }

    public required string DefinitionJson { get; set; }

    /// <summary>Starts at 1 and goes up by one per change. Also the optimistic-concurrency token.</summary>
    public long Version { get; set; }

    public bool Archived { get; set; }

    public long UpdatedAtMs { get; set; }

    public required string UpdatedBy { get; set; }
}

/// <summary>Append-only history: who changed what, when, with the definition before and after.</summary>
public sealed class AuditRecord
{
    public long Id { get; set; }

    public required string Environment { get; set; }

    public required string FlagKey { get; set; }

    public long Version { get; set; }

    public required string Actor { get; set; }

    public required string Action { get; set; }

    public required string Changes { get; set; }

    public string? BeforeJson { get; set; }

    public required string AfterJson { get; set; }

    public long AtMs { get; set; }
}

/// <summary>Exposures rolled up per variant per hour. Raw events are never stored.</summary>
public sealed class ExposureCount
{
    public required string Environment { get; set; }

    public required string FlagKey { get; set; }

    public required string Variant { get; set; }

    public long HourStartMs { get; set; }

    public long Count { get; set; }
}
