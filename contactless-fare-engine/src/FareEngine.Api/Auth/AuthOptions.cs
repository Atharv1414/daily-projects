namespace FareEngine.Api.Auth;

public sealed class AuthOptions
{
    public const string Section = "Auth";

    /// <summary>Reader id to shared secret. Set through the environment, never in a committed file.</summary>
    public Dictionary<string, string> Readers { get; init; } = new(StringComparer.Ordinal);

    public Dictionary<string, StaffKey> Staff { get; init; } = new(StringComparer.Ordinal);

    public int SignatureWindowSeconds { get; set; } = 300;
}

/// <summary>A staff API key is stored only as its SHA-256 hash, in hex.</summary>
public sealed class StaffKey
{
    public string KeySha256 { get; set; } = "";

    public IReadOnlyList<string> Roles { get; init; } = [];
}

public static class Policies
{
    public const string Agent = "agent";
    public const string Finance = "finance";
}
