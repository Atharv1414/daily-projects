using Microsoft.EntityFrameworkCore;

namespace FareEngine.Application.Persistence;

public sealed class FareDbContext(DbContextOptions<FareDbContext> options) : DbContext(options)
{
    public DbSet<TapRecord> Taps => Set<TapRecord>();

    public DbSet<RatingJob> Jobs => Set<RatingJob>();

    public DbSet<LedgerEntry> Ledger => Set<LedgerEntry>();

    public DbSet<SettlementLine> SettlementLines => Set<SettlementLine>();

    public DbSet<SettlementRun> SettlementRuns => Set<SettlementRun>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        ArgumentNullException.ThrowIfNull(modelBuilder);
        modelBuilder.Entity<TapRecord>(e =>
        {
            e.HasKey(x => x.Id);
            e.Property(x => x.Id).ValueGeneratedNever();
            e.Property(x => x.Kind).HasConversion<string>().HasMaxLength(8);
            e.Property(x => x.Source).HasConversion<string>().HasMaxLength(20);
            e.Property(x => x.CardToken).HasMaxLength(64);
            e.Property(x => x.PlaceId).HasMaxLength(32);
            e.HasIndex(x => new { x.CardToken, x.OccurredAtMs });
        });
        modelBuilder.Entity<RatingJob>(e =>
        {
            e.HasKey(x => new { x.CardToken, x.WeekStart });
            e.HasIndex(x => new { x.Dead, x.DueAtMs });
        });
        modelBuilder.Entity<LedgerEntry>(e =>
        {
            e.HasKey(x => x.Id);
            e.Property(x => x.Kind).HasConversion<string>().HasMaxLength(12);
            e.HasIndex(x => new { x.CardToken, x.WeekStart });
            e.HasIndex(x => new { x.SettlementLineId, x.ServiceDate });
            e.HasOne<SettlementLine>().WithMany().HasForeignKey(x => x.SettlementLineId).OnDelete(DeleteBehavior.Restrict);
            e.ToTable(t => t.HasCheckConstraint("CK_Ledger_NonZero", "AmountPence <> 0"));
        });
        modelBuilder.Entity<SettlementLine>(e =>
        {
            e.HasKey(x => x.Id);
            e.HasIndex(x => new { x.SettlementDate, x.CardToken }).IsUnique();
        });
        modelBuilder.Entity<SettlementRun>(e => e.HasKey(x => x.SettlementDate));
    }
}
