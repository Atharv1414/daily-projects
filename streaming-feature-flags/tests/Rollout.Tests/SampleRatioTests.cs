using Rollout.Domain;

namespace Rollout.Tests;

public class SampleRatioTests
{
    [Theory]
    [InlineData(3.841459, 1, 0.05)]
    [InlineData(6.634897, 1, 0.01)]
    [InlineData(5.991465, 2, 0.05)]
    [InlineData(30.143527, 19, 0.05)]
    [InlineData(0.0, 3, 1.0)]
    public void Chi_square_tail_matches_published_tables(double x, int df, double p) =>
        Assert.Equal(p, SampleRatio.ChiSquareSurvival(x, df), precision: 5);

    [Fact]
    public void Log_gamma_is_exact_on_integers() =>
        Assert.Equal(Math.Log(120), SampleRatio.LogGamma(6), precision: 10);

    [Fact]
    public void An_even_split_passes_and_a_lopsided_one_fails()
    {
        Assert.False(SampleRatio.Check([50_120, 49_880], [1, 1]).Mismatch);
        var bad = SampleRatio.Check([51_000, 49_000], [1, 1]);
        Assert.True(bad.Mismatch);
        Assert.True(bad.PValue < 1e-9);
    }

    [Fact]
    public void Traffic_to_a_zero_weight_variant_is_always_a_mismatch()
    {
        var result = SampleRatio.Check([1_000, 1_000, 3], [50, 50, 0]);
        Assert.True(result.Mismatch);
        Assert.Equal(0, result.PValue);
    }

    [Fact]
    public void No_traffic_is_not_a_mismatch_and_bad_input_is_refused()
    {
        Assert.False(SampleRatio.Check([0, 0], [1, 1]).Mismatch);
        Assert.Throws<ArgumentException>(() => SampleRatio.Check([1], [1]));
        Assert.Throws<ArgumentException>(() => SampleRatio.Check([1, 2], [0, 0]));
    }
}
