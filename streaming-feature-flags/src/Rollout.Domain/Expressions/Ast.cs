using System.Collections.Immutable;

namespace Rollout.Domain.Expressions;

/// <summary>A parsed rule. Nodes are immutable so one compiled rule can be shared by every request thread.</summary>
public abstract record Node;

public sealed record LiteralNode(Value Value) : Node;

public sealed record AttributeNode(string Name) : Node;

public sealed record ListNode(ImmutableArray<Node> Items) : Node
{
    public bool Equals(ListNode? other) => other is not null && Items.SequenceEqual(other.Items);

    public override int GetHashCode() => Items.Length;
}

public sealed record CallNode(string Function, ImmutableArray<Node> Arguments) : Node
{
    public bool Equals(CallNode? other) =>
        other is not null && Function == other.Function && Arguments.SequenceEqual(other.Arguments);

    public override int GetHashCode() => HashCode.Combine(Function, Arguments.Length);
}

public sealed record NotNode(Node Operand) : Node;

public sealed record AndNode(Node Left, Node Right) : Node;

public sealed record OrNode(Node Left, Node Right) : Node;

public enum Comparison
{
    Equal,
    NotEqual,
    Less,
    LessOrEqual,
    Greater,
    GreaterOrEqual,
    In,
    NotIn,
    Contains,
    StartsWith,
    EndsWith,
}

public sealed record CompareNode(Node Left, Comparison Op, Node Right) : Node;
