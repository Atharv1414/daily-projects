namespace Rollout.Domain.Expressions;

/// <summary>
/// Evaluates a parsed rule against a context. Rules never throw at evaluation time:
/// a missing attribute is <c>null</c>, and comparing values of different types is simply false.
/// That way a typo in one rule cannot take the snapshot endpoint down for every viewer.
/// </summary>
public static class Interpreter
{
    public static bool Matches(Node rule, EvaluationContext context)
    {
        ArgumentNullException.ThrowIfNull(rule);
        ArgumentNullException.ThrowIfNull(context);
        return Truthy(Eval(rule, context));
    }

    public static Value Eval(Node node, EvaluationContext context)
    {
        ArgumentNullException.ThrowIfNull(node);
        ArgumentNullException.ThrowIfNull(context);
        return node switch
        {
            LiteralNode literal => literal.Value,
            AttributeNode attribute => context.Get(attribute.Name),
            ListNode list => Value.Of(list.Items.Select(i => Eval(i, context))),
            CallNode call => Call(call.Function, Eval(call.Arguments[0], context)),
            NotNode not => Value.Of(!Truthy(Eval(not.Operand, context))),
            AndNode and => Value.Of(Truthy(Eval(and.Left, context)) && Truthy(Eval(and.Right, context))),
            OrNode or => Value.Of(Truthy(Eval(or.Left, context)) || Truthy(Eval(or.Right, context))),
            CompareNode compare => Value.Of(Compare(Eval(compare.Left, context), compare.Op, Eval(compare.Right, context))),
            _ => throw new InvalidOperationException($"Unknown node {node.GetType().Name}"),
        };
    }

    private static bool Truthy(Value value) => value is BoolValue { Flag: true };

    private static Value Call(string function, Value argument) => (function, argument) switch
    {
        ("semver", StringValue s) when SemVer.TryParse(s.Text, out var v) => new VersionValue(v),
        ("semver", VersionValue v) => v,
        ("lower", StringValue s) => Value.Of(s.Text.ToLowerInvariant()),
        ("len", StringValue s) => Value.Of(s.Text.Length),
        ("len", ListValue l) => Value.Of(l.Items.Length),
        _ => Value.Null,
    };

    public static bool Compare(Value left, Comparison op, Value right)
    {
        ArgumentNullException.ThrowIfNull(left);
        ArgumentNullException.ThrowIfNull(right);
        return op switch
        {
            Comparison.Equal => left.Equals(right),
            Comparison.NotEqual => !left.Equals(right) && left is not NullValue,
            Comparison.In => right is ListValue list && list.Items.Contains(left) && left is not NullValue,
            Comparison.NotIn => right is ListValue list && !list.Items.Contains(left) && left is not NullValue,
            Comparison.Contains => (left, right) switch
            {
                (StringValue s, StringValue t) => s.Text.Contains(t.Text, StringComparison.Ordinal),
                (ListValue l, _) => l.Items.Contains(right),
                _ => false,
            },
            Comparison.StartsWith => left is StringValue a && right is StringValue b
                && a.Text.StartsWith(b.Text, StringComparison.Ordinal),
            Comparison.EndsWith => left is StringValue c && right is StringValue d
                && c.Text.EndsWith(d.Text, StringComparison.Ordinal),
            _ => Order(left, right) is { } cmp && op switch
            {
                Comparison.Less => cmp < 0,
                Comparison.LessOrEqual => cmp <= 0,
                Comparison.Greater => cmp > 0,
                Comparison.GreaterOrEqual => cmp >= 0,
                _ => false,
            },
        };
    }

    /// <summary>Only like types are ordered. Strings order by ordinal so results never depend on the server's culture.</summary>
    private static int? Order(Value left, Value right) => (left, right) switch
    {
        (NumberValue a, NumberValue b) when !double.IsNaN(a.Number) && !double.IsNaN(b.Number) => a.Number.CompareTo(b.Number),
        (VersionValue a, VersionValue b) => a.Version.CompareTo(b.Version),
        (StringValue a, StringValue b) => string.CompareOrdinal(a.Text, b.Text),
        _ => null,
    };
}
