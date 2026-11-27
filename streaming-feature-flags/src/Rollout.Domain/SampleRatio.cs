namespace Rollout.Domain;

/// <summary>Result of a sample-ratio-mismatch check on one experiment.</summary>
public sealed record SrmResult(double ChiSquare, int DegreesOfFreedom, double PValue, bool Mismatch, long Total);

/// <summary>
/// Sample ratio mismatch: if a 50/50 test shows 52/48 on large numbers, something upstream
/// (a crash on one variant, caching, a redirect) is dropping viewers, and the experiment's results cannot be trusted.
/// A chi-square goodness-of-fit test against the configured weights catches it.
/// </summary>
public static class SampleRatio
{
    /// <summary>A strict threshold is standard for SRM, because the check runs continuously.</summary>
    public const double DefaultAlpha = 0.001;

    public static SrmResult Check(IReadOnlyList<long> observed, IReadOnlyList<double> expectedShares, double alpha = DefaultAlpha)
    {
        ArgumentNullException.ThrowIfNull(observed);
        ArgumentNullException.ThrowIfNull(expectedShares);
        if (observed.Count != expectedShares.Count || observed.Count < 2)
        {
            throw new ArgumentException("Need at least two groups, with one expected share per observed count.");
        }

        var shareTotal = expectedShares.Sum();
        if (shareTotal <= 0 || expectedShares.Any(s => s < 0))
        {
            throw new ArgumentException("Expected shares must be non-negative and not all zero.", nameof(expectedShares));
        }

        var total = observed.Sum();
        if (total == 0)
        {
            return new SrmResult(0, observed.Count - 1, 1, false, 0);
        }

        double chi = 0;
        var groups = 0;
        for (var i = 0; i < observed.Count; i++)
        {
            var expected = total * expectedShares[i] / shareTotal;
            if (expected == 0)
            {
                if (observed[i] > 0)
                {
                    // Traffic where none was configured is a mismatch by definition.
                    return new SrmResult(double.PositiveInfinity, observed.Count - 1, 0, true, total);
                }

                continue;
            }

            groups++;
            var diff = observed[i] - expected;
            chi += diff * diff / expected;
        }

        var df = Math.Max(1, groups - 1);
        var p = ChiSquareSurvival(chi, df);
        return new SrmResult(chi, df, p, p < alpha, total);
    }

    /// <summary>P(X &gt; x) for a chi-square with k degrees of freedom: the upper regularised gamma Q(k/2, x/2).</summary>
    public static double ChiSquareSurvival(double x, int k)
    {
        if (x <= 0)
        {
            return 1;
        }

        return UpperRegularisedGamma(k / 2.0, x / 2.0);
    }

    private static double UpperRegularisedGamma(double a, double x)
    {
        // Series for small x, continued fraction (Lentz) for large x, as in Numerical Recipes.
        if (x < a + 1)
        {
            double sum = 1 / a, term = sum;
            for (var n = 1; n < 500; n++)
            {
                term *= x / (a + n);
                sum += term;
                if (Math.Abs(term) < Math.Abs(sum) * 1e-15)
                {
                    break;
                }
            }

            return Math.Clamp(1 - (sum * Math.Exp(-x + (a * Math.Log(x)) - LogGamma(a))), 0, 1);
        }

        const double tiny = 1e-300;
        var b = x + 1 - a;
        var c = 1 / tiny;
        var d = 1 / b;
        var h = d;
        for (var i = 1; i < 500; i++)
        {
            var an = -i * (i - a);
            b += 2;
            d = (an * d) + b;
            d = Math.Abs(d) < tiny ? tiny : d;
            c = b + (an / c);
            c = Math.Abs(c) < tiny ? tiny : c;
            d = 1 / d;
            var delta = d * c;
            h *= delta;
            if (Math.Abs(delta - 1) < 1e-15)
            {
                break;
            }
        }

        return Math.Clamp(Math.Exp(-x + (a * Math.Log(x)) - LogGamma(a)) * h, 0, 1);
    }

    /// <summary>Lanczos approximation, accurate to about 15 digits for positive arguments.</summary>
    public static double LogGamma(double x)
    {
        ReadOnlySpan<double> g =
        [
            676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
            12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
        ];
        if (x < 0.5)
        {
            return Math.Log(Math.PI / Math.Abs(Math.Sin(Math.PI * x))) - LogGamma(1 - x);
        }

        x -= 1;
        var sum = 0.99999999999980993;
        for (var i = 0; i < g.Length; i++)
        {
            sum += g[i] / (x + i + 1);
        }

        var t = x + g.Length - 0.5;
        return (0.5 * Math.Log(2 * Math.PI)) + ((x + 0.5) * Math.Log(t)) - t + Math.Log(sum);
    }
}
