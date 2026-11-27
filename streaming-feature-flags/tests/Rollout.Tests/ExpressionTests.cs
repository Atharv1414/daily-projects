using Rollout.Domain;
using Rollout.Domain.Expressions;

namespace Rollout.Tests;

public class ExpressionTests
{
    private static readonly EvaluationContext Viewer = EvaluationContext.Of(
        ("country", Value.Of("GB")),
        ("plan", Value.Of("premium")),
        ("appVersion", Value.Of("7.4.1")),
        ("device.year", Value.Of(2017)),
        ("device.platform", Value.Of("smarttv")),
        ("email", Value.Of("asha@corvid.example")),
        ("segments", Value.Of([Value.Of("sport"), Value.Of("drama")])),
        ("beta", Value.Of(true)));

    [Theory]
    [InlineData("country == \"GB\"", true)]
    [InlineData("country != \"GB\"", false)]
    [InlineData("country in [\"GB\", \"IE\"]", true)]
    [InlineData("country not in [\"GB\", \"IE\"]", false)]
    [InlineData("plan == \"premium\" and device.year < 2019", true)]
    [InlineData("plan == \"basic\" or beta == true", true)]
    [InlineData("not plan == \"premium\"", false)]
    [InlineData("not (plan == \"basic\" or country == \"IE\")", true)]
    [InlineData("semver(appVersion) >= semver(\"7.4.0\")", true)]
    [InlineData("semver(appVersion) >= semver(\"7.10.0\")", false)]
    [InlineData("email endsWith \"@corvid.example\"", true)]
    [InlineData("email startsWith \"asha\"", true)]
    [InlineData("segments contains \"sport\"", true)]
    [InlineData("len(segments) == 2", true)]
    [InlineData("lower(country) == \"gb\"", true)]
    [InlineData("device.year >= 2017 and device.year <= 2017", true)]
    public void Rules_evaluate_as_written(string rule, bool expected) =>
        Assert.Equal(expected, Interpreter.Matches(Parser.Parse(rule), Viewer));

    [Theory]
    [InlineData("missing == \"x\"", false)]
    [InlineData("missing != \"x\"", false)]
    [InlineData("missing == null", true)]
    [InlineData("missing in [\"a\"]", false)]
    [InlineData("missing not in [\"a\"]", false)]
    [InlineData("country > 3", false)]
    [InlineData("semver(plan) > semver(\"1.0.0\")", false)]
    public void Missing_attributes_and_type_mismatches_never_match_by_accident(string rule, bool expected) =>
        Assert.Equal(expected, Interpreter.Matches(Parser.Parse(rule), Viewer));

    [Theory]
    [InlineData("", 0)]
    [InlineData("country ==", 10)]
    [InlineData("country == \"GB", 11)]
    [InlineData("country = \"GB\"", 8)]
    [InlineData("plan in [\"a\" \"b\"]", 13)]
    [InlineData("(plan == \"a\"", 12)]
    [InlineData("country == \"GB\" plan", 16)]
    public void Syntax_errors_point_at_the_problem(string rule, int position)
    {
        var error = Assert.Throws<RuleSyntaxException>(() => Parser.Parse(rule));
        Assert.Equal(position, error.Position);
    }

    [Fact]
    public void Only_allow_listed_functions_can_be_called()
    {
        var error = Assert.Throws<RuleSyntaxException>(() => Parser.Parse("exec(\"rm -rf\") == 1"));
        Assert.Contains("Unknown function 'exec'", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Deep_nesting_and_huge_rules_are_rejected_before_they_cost_anything()
    {
        var deep = new string('(', 40) + "plan == \"a\"" + new string(')', 40);
        Assert.Contains("nest", Assert.Throws<RuleSyntaxException>(() => Parser.Parse(deep)).Message, StringComparison.Ordinal);

        var huge = string.Join(" or ", Enumerable.Repeat("plan == \"premium\"", 200));
        Assert.Contains("limited", Assert.Throws<RuleSyntaxException>(() => Parser.Parse(huge)).Message, StringComparison.Ordinal);
    }

    [Fact]
    public void And_binds_tighter_than_or()
    {
        var node = Parser.Parse("a == 1 or b == 2 and c == 3");
        var or = Assert.IsType<OrNode>(node);
        Assert.IsType<AndNode>(or.Right);
    }

    [Theory]
    [InlineData("7.4.0", "7.4.1", -1)]
    [InlineData("7.10.0", "7.9.9", 1)]
    [InlineData("7.5.0-beta.2", "7.5.0", -1)]
    [InlineData("7.5.0-beta.2", "7.5.0-beta.10", -1)]
    [InlineData("7.5.0-alpha", "7.5.0-beta", -1)]
    [InlineData("v8", "8.0.0+build.5", 0)]
    public void Semantic_versions_order_numerically_with_prereleases_first(string a, string b, int sign)
    {
        Assert.True(SemVer.TryParse(a, out var x));
        Assert.True(SemVer.TryParse(b, out var y));
        Assert.Equal(sign, Math.Sign(x.CompareTo(y)));
    }

    [Fact]
    public void Contexts_flatten_nested_json_and_refuse_oversized_input()
    {
        using var doc = System.Text.Json.JsonDocument.Parse("""{"userId":"u1","device":{"os":"tvos","year":2021},"tags":["a","b"]}""");
        var context = EvaluationContext.FromJson(doc.RootElement);
        Assert.Equal(Value.Of("tvos"), context.Get("device.os"));
        Assert.Equal(Value.Of(2021), context.Get("device.year"));
        Assert.True(Interpreter.Matches(Parser.Parse("tags contains \"b\""), context));

        var many = "{" + string.Join(",", Enumerable.Range(0, 70).Select(i => $"\"a{i}\":{i}")) + "}";
        using var big = System.Text.Json.JsonDocument.Parse(many);
        Assert.Throws<ArgumentException>(() => EvaluationContext.FromJson(big.RootElement));
    }
}
