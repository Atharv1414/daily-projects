namespace Rollout.Domain.Expressions;

/// <summary>
/// Recursive-descent parser for targeting rules, for example
/// <c>country in ["GB", "IE"] and semver(appVersion) >= semver("5.2.0") and not plan == "basic"</c>.
/// Precedence from loosest to tightest: or, and, not, comparison.
/// </summary>
public sealed class Parser
{
    public const int MaxDepth = 32;

    /// <summary>Functions a rule may call. Anything else is a syntax error, so rules cannot reach the host.</summary>
    public static readonly IReadOnlySet<string> Functions = new HashSet<string>(StringComparer.Ordinal)
    {
        "semver", "lower", "len",
    };

    private readonly IReadOnlyList<Token> _tokens;
    private int _index;
    private int _depth;

    private Parser(IReadOnlyList<Token> tokens) => _tokens = tokens;

    public static Node Parse(string text)
    {
        var parser = new Parser(Lexer.Tokenise(text));
        if (parser.Current.Kind == TokenKind.End)
        {
            throw new RuleSyntaxException("A rule cannot be empty", 0);
        }

        var node = parser.ParseOr();
        parser.Expect(TokenKind.End, "Unexpected text after the end of the rule");
        return node;
    }

    private Token Current => _tokens[_index];

    private Token Advance() => _tokens[_index++];

    private bool Match(TokenKind kind)
    {
        if (Current.Kind != kind)
        {
            return false;
        }

        _index++;
        return true;
    }

    private Token Expect(TokenKind kind, string message)
    {
        if (Current.Kind != kind)
        {
            var near = Current.Kind == TokenKind.End ? "end of rule" : $"'{Current.Text}'";
            throw new RuleSyntaxException($"{message}, found {near}", Current.Position);
        }

        return Advance();
    }

    private Node Nested(Func<Node> parse)
    {
        if (++_depth > MaxDepth)
        {
            throw new RuleSyntaxException($"Rules may nest at most {MaxDepth} levels deep", Current.Position);
        }

        try
        {
            return parse();
        }
        finally
        {
            _depth--;
        }
    }

    private Node ParseOr()
    {
        var left = ParseAnd();
        while (Match(TokenKind.Or))
        {
            left = new OrNode(left, ParseAnd());
        }

        return left;
    }

    private Node ParseAnd()
    {
        var left = ParseNot();
        while (Match(TokenKind.And))
        {
            left = new AndNode(left, ParseNot());
        }

        return left;
    }

    private Node ParseNot() =>
        Current.Kind == TokenKind.Not && Peek(1).Kind != TokenKind.In
            ? Nested(() =>
            {
                Advance();
                return new NotNode(ParseNot());
            })
            : ParseComparison();

    private Token Peek(int offset) => _tokens[Math.Min(_index + offset, _tokens.Count - 1)];

    private Node ParseComparison()
    {
        var left = ParsePrimary();
        Comparison? op = Current.Kind switch
        {
            TokenKind.Equal => Comparison.Equal,
            TokenKind.NotEqual => Comparison.NotEqual,
            TokenKind.Less => Comparison.Less,
            TokenKind.LessOrEqual => Comparison.LessOrEqual,
            TokenKind.Greater => Comparison.Greater,
            TokenKind.GreaterOrEqual => Comparison.GreaterOrEqual,
            TokenKind.In => Comparison.In,
            TokenKind.Not when Peek(1).Kind == TokenKind.In => Comparison.NotIn,
            TokenKind.Contains => Comparison.Contains,
            TokenKind.StartsWith => Comparison.StartsWith,
            TokenKind.EndsWith => Comparison.EndsWith,
            _ => null,
        };
        if (op is null)
        {
            return left;
        }

        Advance();
        if (op == Comparison.NotIn)
        {
            Advance();
        }

        var right = ParsePrimary();
        return new CompareNode(left, op.Value, right);
    }

    private Node ParsePrimary()
    {
        var token = Current;
        switch (token.Kind)
        {
            case TokenKind.Text:
                Advance();
                return new LiteralNode(Value.Of(token.Text));
            case TokenKind.Number:
                Advance();
                return new LiteralNode(Value.Of(token.Number));
            case TokenKind.True:
                Advance();
                return new LiteralNode(BoolValue.True);
            case TokenKind.False:
                Advance();
                return new LiteralNode(BoolValue.False);
            case TokenKind.Null:
                Advance();
                return new LiteralNode(Value.Null);
            case TokenKind.LeftParen:
                return Nested(() =>
                {
                    Advance();
                    var inner = ParseOr();
                    Expect(TokenKind.RightParen, "Expected ')'");
                    return inner;
                });
            case TokenKind.LeftBracket:
                return Nested(ParseList);
            case TokenKind.Identifier when Peek(1).Kind == TokenKind.LeftParen:
                return Nested(ParseCall);
            case TokenKind.Identifier:
                Advance();
                return new AttributeNode(token.Text);
            default:
                var found = token.Kind == TokenKind.End ? "end of rule" : $"'{token.Text}'";
                throw new RuleSyntaxException($"Expected a value or attribute, found {found}", token.Position);
        }
    }

    private Node ParseList()
    {
        Advance();
        var items = new List<Node>();
        if (!Match(TokenKind.RightBracket))
        {
            do
            {
                items.Add(ParsePrimary());
            }
            while (Match(TokenKind.Comma));

            Expect(TokenKind.RightBracket, "Expected ']' or ','");
        }

        return new ListNode([.. items]);
    }

    private Node ParseCall()
    {
        var name = Advance();
        if (!Functions.Contains(name.Text))
        {
            throw new RuleSyntaxException(
                $"Unknown function '{name.Text}'. Allowed: {string.Join(", ", Functions.Order(StringComparer.Ordinal))}",
                name.Position);
        }

        Advance();
        var args = new List<Node>();
        if (!Match(TokenKind.RightParen))
        {
            do
            {
                args.Add(ParseOr());
            }
            while (Match(TokenKind.Comma));

            Expect(TokenKind.RightParen, "Expected ')' or ','");
        }

        if (args.Count != 1)
        {
            throw new RuleSyntaxException($"{name.Text}() takes exactly one argument", name.Position);
        }

        return new CallNode(name.Text, [.. args]);
    }
}
