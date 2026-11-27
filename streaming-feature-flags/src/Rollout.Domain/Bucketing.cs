using System.Buffers;
using System.Buffers.Binary;
using System.Numerics;
using System.Text;

namespace Rollout.Domain;

/// <summary>
/// Deterministic bucketing: the same viewer always lands in the same bucket for a flag, on every
/// server and every SDK, without storing assignments. Buckets run from 0 to <see cref="Buckets"/> - 1,
/// so allocations can be set to a thousandth of a percent.
/// </summary>
public static class Bucketing
{
    public const int Buckets = 100_000;

    public static int Bucket(string salt, string flagKey, string unitKey)
    {
        ArgumentNullException.ThrowIfNull(salt);
        ArgumentNullException.ThrowIfNull(flagKey);
        ArgumentNullException.ThrowIfNull(unitKey);
        var length = salt.Length + flagKey.Length + unitKey.Length + 2;
        var maxBytes = Encoding.UTF8.GetMaxByteCount(length);
        byte[]? rented = null;
        var buffer = maxBytes <= 256 ? stackalloc byte[256] : (rented = ArrayPool<byte>.Shared.Rent(maxBytes));
        try
        {
            var written = Encoding.UTF8.GetBytes(salt, buffer);
            buffer[written++] = (byte)'.';
            written += Encoding.UTF8.GetBytes(flagKey, buffer[written..]);
            buffer[written++] = (byte)'.';
            written += Encoding.UTF8.GetBytes(unitKey, buffer[written..]);
            return (int)(Murmur3(buffer[..written], seed: 0) % Buckets);
        }
        finally
        {
            if (rented is not null)
            {
                ArrayPool<byte>.Shared.Return(rented);
            }
        }
    }

    /// <summary>MurmurHash3 x86 32-bit. Small, fast and well distributed; not a security hash, and it does not need to be.</summary>
    public static uint Murmur3(ReadOnlySpan<byte> data, uint seed)
    {
        const uint c1 = 0xcc9e2d51;
        const uint c2 = 0x1b873593;
        var h = seed;
        var blocks = data.Length / 4;
        for (var i = 0; i < blocks; i++)
        {
            var k = BinaryPrimitives.ReadUInt32LittleEndian(data.Slice(i * 4, 4));
            k *= c1;
            k = BitOperations.RotateLeft(k, 15);
            k *= c2;
            h ^= k;
            h = BitOperations.RotateLeft(h, 13);
            h = (h * 5) + 0xe6546b64;
        }

        var tail = data[(blocks * 4)..];
        uint k1 = 0;
        if (tail.Length >= 3)
        {
            k1 ^= (uint)tail[2] << 16;
        }

        if (tail.Length >= 2)
        {
            k1 ^= (uint)tail[1] << 8;
        }

        if (tail.Length >= 1)
        {
            k1 ^= tail[0];
            k1 *= c1;
            k1 = BitOperations.RotateLeft(k1, 15);
            k1 *= c2;
            h ^= k1;
        }

        h ^= (uint)data.Length;
        h ^= h >> 16;
        h *= 0x85ebca6b;
        h ^= h >> 13;
        h *= 0xc2b2ae35;
        h ^= h >> 16;
        return h;
    }
}
