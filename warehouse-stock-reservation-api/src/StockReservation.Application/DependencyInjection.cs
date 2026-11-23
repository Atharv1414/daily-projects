using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using StockReservation.Application.Common;
using StockReservation.Application.Inventory;
using StockReservation.Application.Outbox;
using StockReservation.Application.Persistence;
using StockReservation.Application.Reservations;

namespace StockReservation.Application;

public static class DependencyInjection
{
    /// <summary>Registers persistence, domain services and (optionally) the background workers.</summary>
    public static IServiceCollection AddStockReservation(
        this IServiceCollection services,
        IConfiguration configuration,
        string connectionString)
    {
        services.AddOptions<ReservationOptions>()
            .Bind(configuration.GetSection(ReservationOptions.SectionName))
            .ValidateDataAnnotations()
            .ValidateOnStart();
        services.AddOptions<WorkerOptions>()
            .Bind(configuration.GetSection(WorkerOptions.SectionName))
            .ValidateDataAnnotations()
            .ValidateOnStart();

        services.AddDbContext<StockDbContext>(o => o.UseSqlite(connectionString));
        services.AddSingleton(TimeProvider.System);
        services.AddSingleton<IEventPublisher, LoggingEventPublisher>();
        services.AddScoped<ReservationService>();
        services.AddScoped<InventoryService>();
        services.AddScoped<OutboxDispatcher>();

        if (configuration.GetValue(WorkerOptions.SectionName + ":Enabled", true))
        {
            services.AddHostedService<OutboxPublisherWorker>();
            services.AddHostedService<ReservationExpiryWorker>();
        }

        return services;
    }
}
