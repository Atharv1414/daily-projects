using System.Globalization;
using System.Text;

namespace Rollout.Domain.Expressions;

public enum TokenKind
{
    Identifier,
    Text,
    Number,
    True,
    False,
    Null,
    And,
    Or,
    Not,
    In,
    Contains,
    StartsWith,
    EndsWith,
    Equal,
    NotEqual,
    Less,
    LessOrEqual,
    Greater,
    GreaterOrEqual,
    LeftParen,
    RightParen,
    LeftBracket,
    RightBracket,
    Comma,
    End,
}

public readonly record struct Token(TokenKind Kind, string Text, int Position, double Number = 0);

/// <summary>Thrown for any rule text that cannot be read. Position is a zero-based character offset.</summary>
public sealed class RuleSyntaxException(string message, int position)
    : Exception($"{message} (at character {position + 1})")
{
    public int Position { get; } = position;
}

/// <summary>Turns rule text into tokens. Hand-written so that error positions are exact.</summary>
public static class Lexer
{
    public const int MaxLength = 2_000;

    private static readonly Dictionary<string, TokenKind> Keywords = new(StringComparer.Ordinal)
    {
        ["and"] = TokenKind.And,
        ["or"] = TokenKind.Or,
        ["not"] = TokenKind.Not,
        ["in"] = TokenKind.In,
        ["contains"] = TokenKind.Contains,
        ["startsWith"] = TokenKind.StartsWith,
        ["endsWith"] = TokenKind.EndsWith,
        ["true"] = TokenKind.True,
        ["false"] = TokenKind.False,
        ["null"] = TokenKind.Null,
    };

    public static IReadOnlyList<Token> Tokenise(string text)
    {
        ArgumentNullException.ThrowIfNull(text);
        if (text.Length > MaxLength)
        {
            throw new RuleSyntaxException($"Rules are limited to {MaxLength} characters", MaxLength);
        }

        var tokens = new List<Token>();
        var i = 0;
        while (i < text.Length)
        {
            var c = text[i];
            if (char.IsWhiteSpace(c))
            {
                i++;
                continue;
            }

            var start = i;
            switch (c)
            {
                case '(':
                    tokens.Add(new Token(TokenKind.LeftParen, "(", i++));
                    continue;
                case ')':
                    tokens.Add(new Token(TokenKind.RightParen, ")", i++));
                    continue;
                case '[':
                    tokens.Add(new Token(TokenKind.LeftBracket, "[", i++));
                    continue;
                case ']':
                    tokens.Add(new Token(TokenKind.RightBracket, "]", i++));
                    continue;
                case ',':
                    tokens.Add(new Token(TokenKind.Comma, ",", i++));
                    continue;
                case '=' when Peek(text, i + 1) == '=':
                    tokens.Add(new Token(TokenKind.Equal, "==", i));
                    i += 2;
                    continue;
                case '!' when Peek(text, i + 1) == '=':
                    tokens.Add(new Token(TokenKind.NotEqual, "!=", i));
                    i += 2;
                    continue;
                case '<':
                    tokens.Add(Peek(text, i + 1) == '='
                        ? new Token(TokenKind.LessOrEqual, "<=", i)
                        : new Token(TokenKind.Less, "<", i));
                    i += Peek(text, i + 1) == '=' ? 2 : 1;
                    continue;
                case '>':
                    tokens.Add(Peek(text, i + 1) == '='
                        ? new Token(TokenKind.GreaterOrEqual, ">=", i)
                        : new Token(TokenKind.Greater, ">", i));
                    i += Peek(text, i + 1) == '=' ? 2 : 1;
                    continue;
                case '"':
                    tokens.Add(ReadString(text, ref i));
                    continue;
                default:
                    break;
            }

            if (char.IsAsciiDigit(c) || (c == '-' && char.IsAsciiDigit(Peek(text, i + 1))))
            {
                i++;
                while (i < text.Length && (char.IsAsciiDigit(text[i]) || text[i] == '.'))
                {
                    i++;
                }

                var literal = text[start..i];
                if (!double.TryParse(literal, NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint,
                        CultureInfo.InvariantCulture, out var number))
                {
                    throw new RuleSyntaxException($"'{literal}' is not a number", start);
                }

                tokens.Add(new Token(TokenKind.Number, literal, start, number));
                continue;
            }

            if (char.IsAsciiLetter(c) || c == '_')
            {
                i++;
                while (i < text.Length && (char.IsAsciiLetterOrDigit(text[i]) || text[i] is '_' or '.'))
                {
                    i++;
                }

                var word = text[start..i];
                if (word.EndsWith('.') || word.Contains("..", StringComparison.Ordinal))
                {
                    throw new RuleSyntaxException($"'{word}' is not a valid attribute name", start);
                }

                tokens.Add(Keywords.TryGetValue(word, out var keyword)
                    ? new Token(keyword, word, start)
                    : new Token(TokenKind.Identifier, word, start));
                continue;
            }

            throw new RuleSyntaxException($"Unexpected character '{c}'", i);
        }

        tokens.Add(new Token(TokenKind.End, string.Empty, text.Length));
        return tokens;
    }

    private static char Peek(string text, int index) => index < text.Length ? text[index] : '\0';

    private static Token ReadString(string text, ref int i)
    {
        var start = i++;
        var builder = new StringBuilder();
        while (i < text.Length)
        {
            var c = text[i++];
            if (c == '"')
            {
                return new Token(TokenKind.Text, builder.ToString(), start);
            }

            if (c == '\\')
            {
                if (i >= text.Length)
                {
                    break;
                }

                var escaped = text[i++];
                builder.Append(escaped switch
                {
                    '"' => '"',
                    '\\' => '\\',
                    'n' => '\n',
                    't' => '\t',
                    _ => throw new RuleSyntaxException($"Unknown escape '\\{escaped}'", i - 2),
                });
                continue;
            }

            builder.Append(c);
        }

        throw new RuleSyntaxException("Unterminated string", start);
    }
}
