using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Options;

namespace FareEngine.Api.Auth;

/// <summary>
/// Checks that a batch came from a known reader and was not changed on the way. The signature covers the
/// timestamp and the exact bytes sent; replays inside the window are harmless because taps are idempotent.
/// </summary>
public sealed class ReaderSignature(IOptionsMonitor<AuthOptions> options, TimeProvider clock)
{
    public const string ReaderHeader = "X-Reader-Id";
    public const string TimestampHeader = "X-Timestamp";
    public const string SignatureHeader = "X-Signature";

    public static string Sign(string secret, string readerId, string timestamp, ReadOnlySpan<byte> body)
    {
        using var hmac = IncrementalHash.CreateHMAC(HashAlgorithmName.SHA256, Encoding.UTF8.GetBytes(secret));
        hmac.AppendData(Encoding.UTF8.GetBytes($"{readerId}\n{timestamp}\n"));
        hmac.AppendData(body);
        return Convert.ToHexStringLower(hmac.GetHashAndReset());
    }

    public bool TryVerify(IHeaderDictionary headers, ReadOnlySpan<byte> body, out string readerId)
    {
        ArgumentNullException.ThrowIfNull(headers);
        readerId = headers[ReaderHeader].ToString();
        var timestamp = headers[TimestampHeader].ToString();
        var settings = options.CurrentValue;
        var knownReader = settings.Readers.TryGetValue(readerId, out var secret);

        // Unknown readers are still checked against a dummy secret, so timing does not reveal which ids exist.
        var expected = Encoding.ASCII.GetBytes(Sign(secret ?? "unknown", readerId, timestamp, body));
        var given = Encoding.ASCII.GetBytes(headers[SignatureHeader].ToString());
        var matches = CryptographicOperations.FixedTimeEquals(expected, given);
        var fresh = long.TryParse(timestamp, NumberStyles.None, CultureInfo.InvariantCulture, out var seconds)
            && Math.Abs(clock.GetUtcNow().ToUnixTimeSeconds() - (decimal)seconds) <= settings.SignatureWindowSeconds;
        return knownReader && !string.IsNullOrEmpty(secret) && matches && fresh;
    }
}
