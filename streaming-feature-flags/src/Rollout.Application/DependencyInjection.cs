using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Rollout.Application.Exposures;
using Rollout.Application.Flags;
using Rollout.Application.Persistence;
using Rollout.Application.Snapshots;

namespace Rollout.Application;

public static class DependencyInjection
{
    public static IServiceCollection AddRollout(this IServiceCollection services, string connectionString)
    {
        services.AddOptions<RolloutOptions>()
            .BindConfiguration(RolloutOptions.Section)
            .ValidateDataAnnotations()
            .ValidateOnStart();
        services.TryAddSingleton(TimeProvider.System);
        services.AddSingleton<SqlitePragmas>();
        services.AddDbContext<RolloutDbContext>((sp, o) => o
            .UseSqlite(connectionString)
            .AddInterceptors(sp.GetRequiredService<SqlitePragmas>()));
        services.AddSingleton<SnapshotCache>();
        services.AddSingleton<ExposureBuffer>();
        services.AddSingleton<ExposureFlusher>();
        services.AddScoped<FlagStore>();
        services.AddScoped<ExperimentReports>();
        return services;
    }

    /// <summary>Loads the demo flags into every environment that has none yet.</summary>
    public static async Task SeedDemoAsync(this IServiceProvider services, IEnumerable<string> environments, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(environments);
        await using var scope = services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RolloutDbContext>();
        var store = scope.ServiceProvider.GetRequiredService<FlagStore>();
        foreach (var environment in environments)
        {
            if (await db.Flags.AnyAsync(f => f.Environment == environment, ct))
            {
                continue;
            }

            // Prerequisites first, so validation finds them.
            foreach (var flag in DemoFlags.All().OrderBy(f => f.PrerequisiteList.Count))
            {
                await store.SaveAsync(environment, flag, null, "seed", ct);
            }
        }
    }
}
