using System.Data.Common;
using Microsoft.EntityFrameworkCore.Diagnostics;

namespace FareEngine.Application.Persistence;

/// <summary>WAL lets readers carry on during a write; the busy timeout makes writers queue instead of failing.</summary>
public sealed class SqlitePragmas : DbConnectionInterceptor
{
    private const string Sql = "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=10000; PRAGMA foreign_keys=ON;";

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
