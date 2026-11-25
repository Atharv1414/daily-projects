using FareEngine.Application.Persistence;
using FareEngine.Application.Rating;
using FareEngine.Application.Settlement;
using FareEngine.Application.Taps;
using FareEngine.Domain;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace FareEngine.Application;

public static class DependencyInjection
{
    public static IServiceCollection AddFareEngine(this IServiceCollection services, string connectionString)
    {
        services.AddOptions<FareOptions>()
            .BindConfiguration(FareOptions.Section)
            .ValidateDataAnnotations()
            .ValidateOnStart();
        services.TryAddSingleton(TimeProvider.System);
        services.AddSingleton(NorthmoorNetwork.Create());
        services.AddSingleton(NorthmoorNetwork.Tariffs());
        services.AddSingleton(NorthmoorNetwork.Calendar());
        services.AddSingleton<RatingEngine>();
        services.AddSingleton<RatingSignal>();
        services.AddSingleton<RatingProcessor>();
        services.AddSingleton<SqlitePragmas>();
        services.AddDbContext<FareDbContext>((sp, o) =>
            o.UseSqlite(connectionString).AddInterceptors(sp.GetRequiredService<SqlitePragmas>()));
        services.AddScoped<RatingJobs>();
        services.AddScoped<WeekRater>();
        services.AddScoped<TapIngestion>();
        services.AddScoped<SettlementService>();
        return services;
    }
}
