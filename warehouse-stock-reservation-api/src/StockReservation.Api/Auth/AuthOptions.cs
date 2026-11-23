using System.ComponentModel.DataAnnotations;

namespace StockReservation.Api.Auth;

/// <summary>JWT issuing/validation settings. Override <c>Jwt__SigningKey</c> via environment in any real deployment.</summary>
public sealed class JwtOptions
{
    public const string SectionName = "Jwt";

    [Required]
    public string Issuer { get; set; } = "stock-reservation";

    [Required]
    public string Audience { get; set; } = "stock-reservation-clients";

    [Required]
    [MinLength(32)]
    public string SigningKey { get; set; } = string.Empty;

    [Range(1, 1440)]
    public int TokenMinutes { get; set; } = 60;
}

/// <summary>A demo user. Passwords are stored as PBKDF2 hashes, never in plain text.</summary>
public sealed class DemoUser
{
    public string Username { get; set; } = string.Empty;

    /// <summary>Format: <c>pbkdf2-sha256$iterations$saltBase64$hashBase64</c>.</summary>
    public string PasswordHash { get; set; } = string.Empty;

    public string[] Roles { get; set; } = [];
}

public sealed class UserStoreOptions
{
    public const string SectionName = "Users";

    public List<DemoUser> Accounts { get; set; } = [];
}

public static class Roles
{
    public const string Picker = "picker";
    public const string Planner = "planner";
    public const string Admin = "admin";
}

public static class Policies
{
    /// <summary>Read stock and reservations.</summary>
    public const string CanRead = "can-read";

    /// <summary>Confirm (pick) reservations on the warehouse floor.</summary>
    public const string CanPick = "can-pick";

    /// <summary>Create/release reservations and book goods-in.</summary>
    public const string CanPlan = "can-plan";

    /// <summary>Stock adjustments and operational endpoints.</summary>
    public const string CanAdmin = "can-admin";
}
