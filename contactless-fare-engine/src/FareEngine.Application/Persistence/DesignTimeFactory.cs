using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace FareEngine.Application.Persistence;

/// <summary>Lets <c>dotnet ef</c> create migrations without starting the API.</summary>
public sealed class DesignTimeFactory : IDesignTimeDbContextFactory<FareDbContext>
{
    public FareDbContext CreateDbContext(string[] args) =>
        new(new DbContextOptionsBuilder<FareDbContext>().UseSqlite("Data Source=design.db").Options);
}
