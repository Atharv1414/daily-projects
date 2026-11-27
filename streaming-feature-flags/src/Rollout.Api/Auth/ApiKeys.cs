using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Options;

namespace Rollout.Api.Auth;

/// <summary>A key is stored only as its SHA-256 hash, with the roles and environments it may use.</summary>
public sealed class ApiKeyOptions
{
    public string KeySha256 { get; set; } = string.Empty;

    public IList<string> Roles { get; init; } = [];

    /// <summary>Environments this key may touch. Empty means all (admin keys).</summary>
    public IList<string> Environments { get; init; } = [];
}

public sealed class AuthOptions
{
    public const string Section = "Auth";

    public IDictionary<string, ApiKeyOptions> Keys { get; init; } = new Dictionary<string, ApiKeyOptions>();
}

public static class Roles
{
    /// <summary>Reads flags, history and experiment reports.</summary>
    public const string Viewer = "viewer";

    /// <summary>Changes flags outside production.</summary>
    public const string Editor = "editor";

    /// <summary>Changes flags anywhere, including production.</summary>
    public const string Admin = "admin";

    /// <summary>An app or server SDK: reads its environment's snapshot and reports exposures.</summary>
    public const string Sdk = "sdk";
}

public static class Policies
{
    public const string Read = "read";
    public const string Write = "write";
    public const string Sdk = "sdk";
    public const string EnvironmentClaim = "rollout:env";
    public const string Production = "production";

    public static bool MayUse(this ClaimsPrincipal user, string environment)
    {
        ArgumentNullException.ThrowIfNull(user);
        var allowed = user.FindAll(EnvironmentClaim).Select(c => c.Value).ToList();
        return allowed.Count == 0 || allowed.Contains(environment, StringComparer.Ordinal);
    }

    /// <summary>Editors may change anything except production; only admins release to production.</summary>
    public static bool MayWrite(this ClaimsPrincipal user, string environment)
    {
        ArgumentNullException.ThrowIfNull(user);
        return user.MayUse(environment)
            && (user.IsInRole(Roles.Admin) || (user.IsInRole(Roles.Editor) && environment != Production));
    }

    /// <summary>The environment an SDK key belongs to. SDK keys are issued for exactly one.</summary>
    public static string? SdkEnvironment(this ClaimsPrincipal user)
    {
        ArgumentNullException.ThrowIfNull(user);
        var environments = user.FindAll(EnvironmentClaim).ToList();
        return environments.Count == 1 ? environments[0].Value : null;
    }
}

/// <summary>Authenticates people, tools and SDKs by API key, comparing hashes in constant time.</summary>
public sealed class ApiKeyHandler(
    IOptionsMonitor<AuthenticationSchemeOptions> scheme,
    IOptionsMonitor<AuthOptions> auth,
    ILoggerFactory loggers,
    UrlEncoder encoder) : AuthenticationHandler<AuthenticationSchemeOptions>(scheme, loggers, encoder)
{
    public const string SchemeName = "ApiKey";
    public const string Header = "X-Api-Key";

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        if (!Request.Headers.TryGetValue(Header, out var given) || string.IsNullOrEmpty(given))
        {
            return Task.FromResult(AuthenticateResult.NoResult());
        }

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(given.ToString()));
        foreach (var (name, key) in auth.CurrentValue.Keys)
        {
            if (TryHex(key.KeySha256, out var expected) && CryptographicOperations.FixedTimeEquals(hash, expected))
            {
                var claims = key.Roles.Select(r => new Claim(ClaimTypes.Role, r))
                    .Concat(key.Environments.Select(e => new Claim(Policies.EnvironmentClaim, e)))
                    .Append(new Claim(ClaimTypes.Name, name));
                var identity = new ClaimsIdentity(claims, SchemeName);
                return Task.FromResult(AuthenticateResult.Success(new AuthenticationTicket(new ClaimsPrincipal(identity), SchemeName)));
            }
        }

        return Task.FromResult(AuthenticateResult.Fail("Unknown API key."));
    }

    private static bool TryHex(string hex, out byte[] bytes)
    {
        try
        {
            bytes = Convert.FromHexString(hex);
            return bytes.Length == SHA256.HashSizeInBytes;
        }
        catch (FormatException)
        {
            bytes = [];
            return false;
        }
    }
}
