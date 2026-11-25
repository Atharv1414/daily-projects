using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Options;

namespace FareEngine.Api.Auth;

/// <summary>Authenticates staff and back-office systems by API key.</summary>
public sealed class StaffKeyHandler(
    IOptionsMonitor<AuthenticationSchemeOptions> scheme,
    IOptionsMonitor<AuthOptions> auth,
    ILoggerFactory loggers,
    UrlEncoder encoder) : AuthenticationHandler<AuthenticationSchemeOptions>(scheme, loggers, encoder)
{
    public const string SchemeName = "StaffKey";
    public const string Header = "X-Api-Key";

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        if (!Request.Headers.TryGetValue(Header, out var given))
        {
            return Task.FromResult(AuthenticateResult.NoResult());
        }

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(given.ToString()));
        foreach (var (name, key) in auth.CurrentValue.Staff)
        {
            if (TryHex(key.KeySha256, out var expected) && CryptographicOperations.FixedTimeEquals(hash, expected))
            {
                var claims = key.Roles.Select(r => new Claim(ClaimTypes.Role, r)).Append(new Claim(ClaimTypes.Name, name));
                var identity = new ClaimsIdentity(claims, SchemeName);
                return Task.FromResult(AuthenticateResult.Success(
                    new AuthenticationTicket(new ClaimsPrincipal(identity), SchemeName)));
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
