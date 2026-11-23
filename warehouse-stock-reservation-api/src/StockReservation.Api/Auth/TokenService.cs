using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;

namespace StockReservation.Api.Auth;

public sealed record TokenResponse(string AccessToken, string TokenType, int ExpiresIn, string[] Roles);

/// <summary>Validates demo credentials and issues short-lived HMAC-SHA256 signed JWTs.</summary>
public sealed class TokenService(IOptions<JwtOptions> jwt, IOptions<UserStoreOptions> users, TimeProvider clock)
{
    public TokenResponse? Issue(string username, string password)
    {
        var user = users.Value.Accounts.FirstOrDefault(
            u => string.Equals(u.Username, username, StringComparison.OrdinalIgnoreCase));
        // Always run the hash so response time does not reveal whether the username exists.
        var hash = user?.PasswordHash ?? PasswordHasher.Hash("timing-equaliser", new byte[16]);
        if (!PasswordHasher.Verify(password, hash) || user is null)
        {
            return null;
        }

        var opts = jwt.Value;
        var now = clock.GetUtcNow();
        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, user.Username),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString("N")),
            new(ClaimTypes.Name, user.Username),
        };
        claims.AddRange(user.Roles.Select(r => new Claim(ClaimTypes.Role, r)));

        var credentials = new SigningCredentials(SigningKey(opts), SecurityAlgorithms.HmacSha256);
        var token = new JwtSecurityToken(
            opts.Issuer,
            opts.Audience,
            claims,
            notBefore: now.UtcDateTime,
            expires: now.AddMinutes(opts.TokenMinutes).UtcDateTime,
            signingCredentials: credentials);
        return new TokenResponse(
            new JwtSecurityTokenHandler().WriteToken(token), "Bearer", opts.TokenMinutes * 60, user.Roles);
    }

    public static SymmetricSecurityKey SigningKey(JwtOptions opts) => new(Encoding.UTF8.GetBytes(opts.SigningKey));
}
