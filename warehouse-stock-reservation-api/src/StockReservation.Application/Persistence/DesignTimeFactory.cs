using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace StockReservation.Application.Persistence;

/// <summary>Lets <c>dotnet ef migrations add</c> build the model without starting the web host.</summary>
public sealed class DesignTimeFactory : IDesignTimeDbContextFactory<StockDbContext>
{
    public StockDbContext CreateDbContext(string[] args) =>
        new(new DbContextOptionsBuilder<StockDbContext>().UseSqlite("Data Source=design.db").Options);
}
