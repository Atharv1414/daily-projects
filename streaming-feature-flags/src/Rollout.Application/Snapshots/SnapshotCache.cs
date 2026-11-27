using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Rollout.Application.Persistence;
using Rollout.Domain;

namespace Rollout.Application.Snapshots;

/// <summary>Everything an SDK needs to evaluate flags locally, built once and served to every poller.</summary>
public sealed record Snapshot(string Environment, FlagSet Flags, string ETag, byte[] Json, DateTimeOffset BuiltAt);

/// <summary>The serialised form of a snapshot: what SDKs download.</summary>
public sealed record SnapshotDocument(string Environment, string ETag, DateTimeOffset BuiltAt, IReadOnlyList<VersionedFlag> Flags);

public sealed record VersionedFlag(long Version, FlagDefinition Definition);

/// <summary>
/// Caches one compiled snapshot per environment. Thousands of TVs poll this, and flags change a few
/// times a day, so reads must not touch the database.
/// <para>
/// Each environment has a generation number. A write bumps it after committing; a snapshot is only served
/// while its generation is current. A build that started before the commit may finish after it, but it
/// carries the old generation and is thrown away, so a reader can never be handed a stale set for good.
/// </para>
/// </summary>
public sealed class SnapshotCache(IServiceScopeFactory scopes, TimeProvider clock)
{
    private readonly ConcurrentDictionary<string, Entry> _entries = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, long> _generations = new(StringComparer.Ordinal);
    private long _builds;

    /// <summary>How many times a snapshot was built from the database. Tests use it to prove caching.</summary>
    public long Builds => Interlocked.Read(ref _builds);

    public async Task<Snapshot> GetAsync(string environment, CancellationToken ct = default)
    {
        while (true)
        {
            var generation = _generations.GetOrAdd(environment, 0);
            var entry = _entries.AddOrUpdate(
                environment,
                _ => new Entry(generation, Build(environment)),
                (_, existing) => existing.Generation == generation ? existing : new Entry(generation, Build(environment)));
            Snapshot snapshot;
            try
            {
                snapshot = await entry.Task.Value.WaitAsync(ct);
            }
            catch (Exception) when (!ct.IsCancellationRequested)
            {
                // A failed build must not be cached; the next caller tries again.
                _entries.TryRemove(new KeyValuePair<string, Entry>(environment, entry));
                throw;
            }

            if (_generations.GetValueOrDefault(environment) == entry.Generation)
            {
                return snapshot;
            }
        }
    }

    public void Invalidate(string environment) => _generations.AddOrUpdate(environment, 1, (_, g) => g + 1);

    private Lazy<Task<Snapshot>> Build(string environment) => new(async () =>
    {
        Interlocked.Increment(ref _builds);
        await using var scope = scopes.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RolloutDbContext>();
        var rows = await db.Flags.AsNoTracking()
            .Where(f => f.Environment == environment && !f.Archived)
            .OrderBy(f => f.Key)
            .Select(f => new { f.Key, f.Version, f.DefinitionJson })
            .ToListAsync();
        var flags = rows
            .Select(r => new VersionedFlag(r.Version, JsonSerializer.Deserialize<FlagDefinition>(r.DefinitionJson, FlagJson.Options)!))
            .ToList();
        var etag = ETagFor(environment, rows.Select(r => (r.Key, r.Version)));
        var builtAt = clock.GetUtcNow();
        var json = JsonSerializer.SerializeToUtf8Bytes(new SnapshotDocument(environment, etag, builtAt, flags), FlagJson.Options);
        return new Snapshot(environment, FlagSet.Compile(flags.Select(f => (f.Definition, f.Version))), etag, json, builtAt);
    }, LazyThreadSafetyMode.ExecutionAndPublication);

    /// <summary>A strong ETag from the keys and versions alone: identical content always has the same tag on every server.</summary>
    public static string ETagFor(string environment, IEnumerable<(string Key, long Version)> flags)
    {
        ArgumentNullException.ThrowIfNull(flags);
        var text = new StringBuilder(environment);
        foreach (var (key, version) in flags)
        {
            text.Append('|').Append(key).Append(':').Append(version);
        }

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(text.ToString()));
        return $"\"{Convert.ToHexStringLower(hash.AsSpan(0, 10))}\"";
    }

    private sealed record Entry(long Generation, Lazy<Task<Snapshot>> Task);
}
