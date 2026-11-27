using System.Globalization;

namespace Rollout.Domain;

/// <summary>Major.minor.patch with an optional pre-release tag. Build metadata is ignored, as semver.org says.</summary>
public readonly record struct SemVer(int Major, int Minor, int Patch, string PreRelease) : IComparable<SemVer>
{
    public static bool TryParse(string? text, out SemVer version)
    {
        version = default;
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        var core = text.Trim().TrimStart('v');
        var plus = core.IndexOf('+', StringComparison.Ordinal);
        if (plus >= 0)
        {
            core = core[..plus];
        }

        var pre = string.Empty;
        var dash = core.IndexOf('-', StringComparison.Ordinal);
        if (dash >= 0)
        {
            pre = core[(dash + 1)..];
            core = core[..dash];
            if (pre.Length == 0)
            {
                return false;
            }
        }

        var parts = core.Split('.');
        if (parts.Length is < 1 or > 3)
        {
            return false;
        }

        Span<int> numbers = [0, 0, 0];
        for (var i = 0; i < parts.Length; i++)
        {
            if (!int.TryParse(parts[i], NumberStyles.None, CultureInfo.InvariantCulture, out numbers[i]))
            {
                return false;
            }
        }

        version = new SemVer(numbers[0], numbers[1], numbers[2], pre);
        return true;
    }

    public int CompareTo(SemVer other)
    {
        var byNumbers = (Major, Minor, Patch).CompareTo((other.Major, other.Minor, other.Patch));
        if (byNumbers != 0)
        {
            return byNumbers;
        }

        // A release outranks any of its pre-releases.
        return (PreRelease.Length == 0, other.PreRelease.Length == 0) switch
        {
            (true, true) => 0,
            (true, false) => 1,
            (false, true) => -1,
            _ => ComparePreRelease(PreRelease, other.PreRelease),
        };
    }

    public override string ToString() =>
        PreRelease.Length == 0 ? $"{Major}.{Minor}.{Patch}" : $"{Major}.{Minor}.{Patch}-{PreRelease}";

    public static bool operator <(SemVer left, SemVer right) => left.CompareTo(right) < 0;

    public static bool operator >(SemVer left, SemVer right) => left.CompareTo(right) > 0;

    public static bool operator <=(SemVer left, SemVer right) => left.CompareTo(right) <= 0;

    public static bool operator >=(SemVer left, SemVer right) => left.CompareTo(right) >= 0;

    private static int ComparePreRelease(string a, string b)
    {
        var x = a.Split('.');
        var y = b.Split('.');
        for (var i = 0; i < Math.Min(x.Length, y.Length); i++)
        {
            var xNumeric = int.TryParse(x[i], NumberStyles.None, CultureInfo.InvariantCulture, out var xn);
            var yNumeric = int.TryParse(y[i], NumberStyles.None, CultureInfo.InvariantCulture, out var yn);
            var cmp = (xNumeric, yNumeric) switch
            {
                (true, true) => xn.CompareTo(yn),
                (true, false) => -1,
                (false, true) => 1,
                _ => string.CompareOrdinal(x[i], y[i]),
            };
            if (cmp != 0)
            {
                return cmp;
            }
        }

        return x.Length.CompareTo(y.Length);
    }
}
