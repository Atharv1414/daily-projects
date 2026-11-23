using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using StockReservation.Domain;

namespace StockReservation.Application.Persistence;

public sealed class StockDbContext(DbContextOptions<StockDbContext> options) : DbContext(options)
{
    public DbSet<StockItem> StockItems => Set<StockItem>();

    public DbSet<Reservation> Reservations => Set<Reservation>();

    public DbSet<StockMovement> Movements => Set<StockMovement>();

    public DbSet<OutboxMessage> Outbox => Set<OutboxMessage>();

    protected override void ConfigureConventions(ModelConfigurationBuilder configurationBuilder)
    {
        // SQLite has no native DateTimeOffset type, so EF cannot compare or order it.
        // Storing UTC Unix milliseconds keeps range filters and ORDER BY in SQL.
        configurationBuilder.Properties<DateTimeOffset>().HaveConversion<UnixMillisecondsConverter>();
        configurationBuilder.Properties<DateTimeOffset?>().HaveConversion<UnixMillisecondsConverter>();
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<StockItem>(e =>
        {
            e.ToTable("stock_items");
            e.HasKey(x => x.Id);
            e.Property(x => x.WarehouseCode).HasMaxLength(8).IsRequired();
            e.Property(x => x.Sku).HasMaxLength(32).IsRequired();
            e.Property(x => x.Description).HasMaxLength(200);
            e.Property(x => x.Version).IsConcurrencyToken();
            e.Ignore(x => x.Available);
            e.Ignore(x => x.IsBelowReorderPoint);
            e.HasIndex(x => new { x.WarehouseCode, x.Sku }).IsUnique();
            e.ToTable(t =>
            {
                t.HasCheckConstraint("ck_stock_reserved_bounds", "\"Reserved\" >= 0 AND \"Reserved\" <= \"OnHand\"");
                t.HasCheckConstraint("ck_stock_reorder_nonnegative", "\"ReorderPoint\" >= 0");
            });
        });

        modelBuilder.Entity<Reservation>(e =>
        {
            e.ToTable("reservations");
            e.HasKey(x => x.Id);
            e.Property(x => x.OrderReference).HasMaxLength(64).IsRequired();
            e.Property(x => x.WarehouseCode).HasMaxLength(8).IsRequired();
            e.Property(x => x.IdempotencyKey).HasMaxLength(100).IsRequired();
            e.Property(x => x.RequestFingerprint).HasMaxLength(64).IsRequired();
            e.Property(x => x.CreatedBy).HasMaxLength(64).IsRequired();
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(16);
            e.Property(x => x.Version).IsConcurrencyToken();
            e.Ignore(x => x.TotalUnits);
            e.HasMany(x => x.Lines).WithOne().HasForeignKey(l => l.ReservationId).OnDelete(DeleteBehavior.Cascade);
            e.Navigation(x => x.Lines).HasField("_lines").UsePropertyAccessMode(PropertyAccessMode.Field);
            e.HasIndex(x => x.IdempotencyKey).IsUnique();
            e.HasIndex(x => new { x.Status, x.ExpiresAt });
            e.HasIndex(x => x.OrderReference);
        });

        modelBuilder.Entity<ReservationLine>(e =>
        {
            e.ToTable("reservation_lines");
            e.HasKey(x => x.Id);
            e.Property(x => x.Sku).HasMaxLength(32).IsRequired();
        });

        modelBuilder.Entity<StockMovement>(e =>
        {
            e.ToTable("stock_movements");
            e.HasKey(x => x.Id);
            e.Property(x => x.Type).HasConversion<string>().HasMaxLength(16);
            e.Property(x => x.Sku).HasMaxLength(32);
            e.Property(x => x.WarehouseCode).HasMaxLength(8);
            e.Property(x => x.Actor).HasMaxLength(64);
            e.Property(x => x.Note).HasMaxLength(200);
            e.HasIndex(x => new { x.StockItemId, x.OccurredAt });
            e.HasIndex(x => x.ReservationId);
        });

        modelBuilder.Entity<OutboxMessage>(e =>
        {
            e.ToTable("outbox_messages");
            e.HasKey(x => x.Id);
            e.Property(x => x.Type).HasMaxLength(64).IsRequired();
            e.Property(x => x.Status).HasConversion<string>().HasMaxLength(16);
            e.Property(x => x.LastError).HasMaxLength(500);
            e.HasIndex(x => new { x.Status, x.NextAttemptAt });
        });
    }
}

/// <summary>Maps <see cref="DateTimeOffset"/> to UTC Unix milliseconds.</summary>
public sealed class UnixMillisecondsConverter() : ValueConverter<DateTimeOffset, long>(
    v => v.ToUnixTimeMilliseconds(),
    v => DateTimeOffset.FromUnixTimeMilliseconds(v));
