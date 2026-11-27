using System.Data.Common;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;
using Microsoft.EntityFrameworkCore.Diagnostics;

namespace Rollout.Application.Persistence;

public sealed class RolloutDbContext(DbContextOptions<RolloutDbContext> options) : DbContext(options)
{
    public DbSet<FlagRecord> Flags => Set<FlagRecord>();

    public DbSet<AuditRecord> Audit => Set<AuditRecord>();

    public DbSet<ExposureCount> Exposures => Set<ExposureCount>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        ArgumentNullException.ThrowIfNull(modelBuilder);
        modelBuilder.Entity<FlagRecord>(e =>
        {
            e.HasKey(x => x.Id);
            e.Property(x => x.Environment).HasMaxLength(32);
            e.Property(x => x.Key).HasMaxLength(64);
            e.Property(x => x.UpdatedBy).HasMaxLength(64);
            e.Property(x => x.Version).IsConcurrencyToken();
            e.HasIndex(x => new { x.Environment, x.Key }).IsUnique();
            e.ToTable(t => t.HasCheckConstraint("CK_Flags_Version", "Version >= 1"));
        });
        modelBuilder.Entity<AuditRecord>(e =>
        {
            e.HasKey(x => x.Id);
            e.Property(x => x.Environment).HasMaxLength(32);
            e.Property(x => x.FlagKey).HasMaxLength(64);
            e.Property(x => x.Actor).HasMaxLength(64);
            e.Property(x => x.Action).HasMaxLength(16);
            e.HasIndex(x => new { x.Environment, x.FlagKey, x.Version }).IsUnique();
        });
        modelBuilder.Entity<ExposureCount>(e =>
        {
            e.HasKey(x => new { x.Environment, x.FlagKey, x.Variant, x.HourStartMs });
            e.Property(x => x.Environment).HasMaxLength(32);
            e.Property(x => x.FlagKey).HasMaxLength(64);
            e.Property(x => x.Variant).HasMaxLength(64);
            e.ToTable(t => t.HasCheckConstraint("CK_Exposures_Count", "Count > 0"));
        });
    }
}

/// <summary>Lets <c>dotnet ef</c> create migrations without starting the API.</summary>
public sealed class DesignTimeFactory : IDesignTimeDbContextFactory<RolloutDbContext>
{
    public RolloutDbContext CreateDbContext(string[] args) =>
        new(new DbContextOptionsBuilder<RolloutDbContext>().UseSqlite("Data Source=design.db").Options);
}

/// <summary>WAL lets snapshot reads carry on during a write; the busy timeout makes writers queue instead of failing.</summary>
public sealed class SqlitePragmas : DbConnectionInterceptor
{
    private const string Sql = "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;";

    public override void ConnectionOpened(DbConnection connection, ConnectionEndEventData eventData)
    {
        ArgumentNullException.ThrowIfNull(connection);
        using var command = connection.CreateCommand();
        command.CommandText = Sql;
        command.ExecuteNonQuery();
    }

    public override async Task ConnectionOpenedAsync(
        DbConnection connection, ConnectionEndEventData eventData, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(connection);
        await using var command = connection.CreateCommand();
        command.CommandText = Sql;
        await command.ExecuteNonQueryAsync(cancellationToken);
    }
}
