using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Rollout.Application.Persistence;
using Rollout.Application.Snapshots;
using Rollout.Domain;

namespace Rollout.Application.Flags;

public sealed record StoredFlag(string Environment, long Version, DateTimeOffset UpdatedAt, string UpdatedBy, FlagDefinition Definition);

public sealed record FlagSummary(string Key, long Version, bool On, string Kind, int Rules, IReadOnlyList<string> Tags, DateTimeOffset UpdatedAt);

public sealed record Page<T>(IReadOnlyList<T> Items, string? NextCursor);

public sealed record AuditEntry(long Version, string Actor, string Action, IReadOnlyList<string> Changes, DateTimeOffset At);

/// <summary>
/// Writes flags. Every change is validated, version-checked, audited and committed in one transaction,
/// and then the environment's snapshot is invalidated.
/// </summary>
public sealed partial class FlagStore(
    RolloutDbContext db,
    SnapshotCache snapshots,
    TimeProvider clock,
    IOptions<RolloutOptions> options,
    ILogger<FlagStore> logger)
{
    private const int ToggleAttempts = 3;
    private readonly RolloutOptions _options = options.Value;

    public void RequireEnvironment(string environment)
    {
        if (!_options.Environments.Contains(environment, StringComparer.Ordinal))
        {
            throw new UnknownEnvironmentException(environment);
        }
    }

    public async Task<StoredFlag> GetAsync(string environment, string key, CancellationToken ct = default)
    {
        RequireEnvironment(environment);
        var record = await db.Flags.AsNoTracking()
            .SingleOrDefaultAsync(f => f.Environment == environment && f.Key == key && !f.Archived, ct)
            ?? throw new FlagNotFoundException(environment, key);
        return ToStored(record);
    }

    /// <summary>Keyset pagination on the flag key: stable while flags are added, and cheap at any depth.</summary>
    public async Task<Page<FlagSummary>> ListAsync(
        string environment, string? search, string? tag, string? cursor, int limit, CancellationToken ct = default)
    {
        RequireEnvironment(environment);
        limit = Math.Clamp(limit, 1, _options.MaxPageSize);
        var query = db.Flags.AsNoTracking().Where(f => f.Environment == environment && !f.Archived);
        if (!string.IsNullOrWhiteSpace(search))
        {
            query = query.Where(f => f.Key.Contains(search));
        }

        // Tags live inside the JSON, so they are filtered in memory; keep reading batches until the page is full.
        const int batchSize = 200;
        var items = new List<FlagSummary>();
        var after = cursor;
        var exhausted = false;
        while (items.Count <= limit && !exhausted)
        {
            // string.Compare is what EF translates to SQL "<"/">"; SQLite's default collation is already binary (ordinal).
#pragma warning disable CA1309
            var page = after is null ? query : query.Where(f => string.Compare(f.Key, after) > 0);
#pragma warning restore CA1309
            var batch = await page.OrderBy(f => f.Key).Take(batchSize).ToListAsync(ct);
            exhausted = batch.Count < batchSize;
            foreach (var record in batch)
            {
                after = record.Key;
                var flag = ToStored(record);
                var tags = flag.Definition.Tags ?? [];
                if (tag is null || tags.Contains(tag, StringComparer.Ordinal))
                {
                    items.Add(new FlagSummary(flag.Definition.Key, flag.Version, flag.Definition.On,
                        flag.Definition.Kind.ToString().ToLowerInvariant(), flag.Definition.RuleList.Count, tags, flag.UpdatedAt));
                }

                if (items.Count > limit)
                {
                    break;
                }
            }
        }

        var hasMore = items.Count > limit;
        if (hasMore)
        {
            items.RemoveAt(items.Count - 1);
        }

        return new Page<FlagSummary>(items, hasMore ? items[^1].Key : null);
    }

    /// <summary>
    /// Creates or replaces a flag. <paramref name="expectedVersion"/> is the version the author last read:
    /// null means "create", and changing an existing flag without one is refused rather than silently overwriting.
    /// </summary>
    public async Task<StoredFlag> SaveAsync(
        string environment, FlagDefinition definition, long? expectedVersion, string actor, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(definition);
        RequireEnvironment(environment);
        var errors = FlagValidator.Validate(definition).ToList();
        if (errors.Count > 0)
        {
            throw new FlagValidationException(errors);
        }

        var others = await LoadDefinitionsAsync(environment, except: definition.Key, ct);
        errors.AddRange(FlagValidator.ValidateInSet(definition, others));
        if (errors.Count > 0)
        {
            throw new FlagValidationException(errors);
        }

        var existing = await db.Flags.SingleOrDefaultAsync(f => f.Environment == environment && f.Key == definition.Key, ct);
        if (existing is not null && !existing.Archived && expectedVersion is null)
        {
            throw new VersionRequiredException(definition.Key);
        }

        if (existing is null or { Archived: true } && expectedVersion is not null and not 0)
        {
            throw new VersionConflictException(definition.Key, expectedVersion, 0);
        }

        if (existing is { Archived: false } && existing.Version != expectedVersion)
        {
            throw new VersionConflictException(definition.Key, expectedVersion, existing.Version);
        }

        var action = existing is null or { Archived: true } ? "create" : "update";
        var before = existing is { Archived: false } ? Parse(existing.DefinitionJson) : null;
        return await CommitAsync(environment, existing, before, definition, action, actor, ct);
    }

    /// <summary>
    /// The kill switch. Deliberately needs no version: in an incident nobody should have to reload a page
    /// before turning a broken feature off. It retries if another write lands in between.
    /// </summary>
    public async Task<StoredFlag> SetOnAsync(string environment, string key, bool on, string actor, CancellationToken ct = default)
    {
        RequireEnvironment(environment);
        for (var attempt = 1; ; attempt++)
        {
            var existing = await db.Flags.SingleOrDefaultAsync(f => f.Environment == environment && f.Key == key && !f.Archived, ct)
                ?? throw new FlagNotFoundException(environment, key);
            var before = Parse(existing.DefinitionJson);
            if (before.On == on)
            {
                return ToStored(existing);
            }

            try
            {
                return await CommitAsync(environment, existing, before, before with { On = on }, on ? "enable" : "disable", actor, ct);
            }
            catch (VersionConflictException) when (attempt < ToggleAttempts)
            {
                db.ChangeTracker.Clear();
            }
        }
    }

    /// <summary>Archives a flag so SDKs stop receiving it. History is kept.</summary>
    public async Task ArchiveAsync(string environment, string key, long expectedVersion, string actor, CancellationToken ct = default)
    {
        RequireEnvironment(environment);
        var existing = await db.Flags.SingleOrDefaultAsync(f => f.Environment == environment && f.Key == key && !f.Archived, ct)
            ?? throw new FlagNotFoundException(environment, key);
        if (existing.Version != expectedVersion)
        {
            throw new VersionConflictException(key, expectedVersion, existing.Version);
        }

        var dependants = (await LoadDefinitionsAsync(environment, except: key, ct)).Values
            .Where(d => d.PrerequisiteList.Any(p => p.FlagKey == key))
            .Select(d => d.Key)
            .Order(StringComparer.Ordinal)
            .ToList();
        if (dependants.Count > 0)
        {
            throw new FlagInUseException(key, dependants);
        }

        var definition = Parse(existing.DefinitionJson);
        await CommitAsync(environment, existing, definition, definition, "archive", actor, ct, archive: true);
    }

    /// <summary>
    /// Copies a flag's targeting from one environment to another (staging to production, say) while keeping the
    /// target's on/off state, so promotion never switches anything on by itself.
    /// </summary>
    public async Task<StoredFlag> PromoteAsync(string from, string to, string key, string actor, CancellationToken ct = default)
    {
        var source = await GetAsync(from, key, ct);
        RequireEnvironment(to);
        var target = await db.Flags.AsNoTracking().SingleOrDefaultAsync(f => f.Environment == to && f.Key == key && !f.Archived, ct);
        var on = target is not null && Parse(target.DefinitionJson).On;
        return await SaveAsync(to, source.Definition with { On = on }, target?.Version, actor, ct);
    }

    public async Task<IReadOnlyList<AuditEntry>> HistoryAsync(string environment, string key, int limit, CancellationToken ct = default)
    {
        RequireEnvironment(environment);
        var rows = await db.Audit.AsNoTracking()
            .Where(a => a.Environment == environment && a.FlagKey == key)
            .OrderByDescending(a => a.Version)
            .Take(Math.Clamp(limit, 1, _options.MaxPageSize))
            .ToListAsync(ct);
        return [.. rows.Select(r => new AuditEntry(r.Version, r.Actor, r.Action, r.Changes.Split('\n'), DateTimeOffset.FromUnixTimeMilliseconds(r.AtMs)))];
    }

    private async Task<StoredFlag> CommitAsync(
        string environment,
        FlagRecord? existing,
        FlagDefinition? before,
        FlagDefinition after,
        string action,
        string actor,
        CancellationToken ct,
        bool archive = false)
    {
        var now = clock.GetUtcNow();
        var json = JsonSerializer.Serialize(after, FlagJson.Options);
        var record = existing ?? new FlagRecord { Environment = environment, Key = after.Key, DefinitionJson = json, UpdatedBy = actor };
        var version = record.Version + 1;
        record.DefinitionJson = json;
        record.Version = version;
        record.Archived = archive;
        record.UpdatedAtMs = now.ToUnixTimeMilliseconds();
        record.UpdatedBy = actor;
        if (existing is null)
        {
            db.Flags.Add(record);
        }

        var changes = archive ? ["Archived."] : FlagDiff.Describe(before, after);
        db.Audit.Add(new AuditRecord
        {
            Environment = environment,
            FlagKey = after.Key,
            Version = version,
            Actor = actor,
            Action = action,
            Changes = string.Join('\n', changes.Count == 0 ? ["No effective change."] : changes),
            BeforeJson = before is null ? null : JsonSerializer.Serialize(before, FlagJson.Options),
            AfterJson = json,
            AtMs = now.ToUnixTimeMilliseconds(),
        });

        try
        {
            await using var transaction = await db.Database.BeginTransactionAsync(ct);
            await db.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);
        }
        catch (DbUpdateException)
        {
            // Another writer got there first. Depending on statement order, that shows up either as the version
            // token not matching (a concurrency exception) or as the audit row's unique (flag, version) index, or
            // as the unique (environment, key) index when two creates race. All mean the same: the version moved.
            db.ChangeTracker.Clear();
            var current = await db.Flags.AsNoTracking().Where(f => f.Environment == environment && f.Key == after.Key)
                .Select(f => (long?)f.Version).SingleOrDefaultAsync(ct);
            if (current is null || current == version - 1)
            {
                throw;
            }

            throw new VersionConflictException(after.Key, existing is null ? null : version - 1, current.Value);
        }

        snapshots.Invalidate(environment);
        LogChanged(logger, environment, after.Key, version, action, actor);
        return ToStored(record);
    }

    private async Task<Dictionary<string, FlagDefinition>> LoadDefinitionsAsync(string environment, string except, CancellationToken ct)
    {
        var rows = await db.Flags.AsNoTracking()
            .Where(f => f.Environment == environment && !f.Archived && f.Key != except)
            .Select(f => f.DefinitionJson)
            .ToListAsync(ct);
        return rows.Select(Parse).ToDictionary(d => d.Key, StringComparer.Ordinal);
    }

    private static FlagDefinition Parse(string json) => JsonSerializer.Deserialize<FlagDefinition>(json, FlagJson.Options)!;

    private static StoredFlag ToStored(FlagRecord record) => new(
        record.Environment, record.Version, DateTimeOffset.FromUnixTimeMilliseconds(record.UpdatedAtMs), record.UpdatedBy, Parse(record.DefinitionJson));

    [LoggerMessage(Level = LogLevel.Information, Message = "{Environment}/{Key} is now v{Version} ({Action} by {Actor})")]
    private static partial void LogChanged(ILogger logger, string environment, string key, long version, string action, string actor);
}
