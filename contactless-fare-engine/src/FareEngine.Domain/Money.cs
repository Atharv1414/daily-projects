using System.Globalization;

namespace FareEngine.Domain;

/// <summary>An amount in whole pence. Fares never touch floating point.</summary>
public readonly record struct Money(long Pence) : IComparable<Money>
{
    public static readonly Money Zero = new(0);

    public static Money Min(Money a, Money b) => a.Pence <= b.Pence ? a : b;

    public static Money Sum(IEnumerable<Money> amounts)
    {
        ArgumentNullException.ThrowIfNull(amounts);
        return new Money(amounts.Sum(a => a.Pence));
    }

    public int CompareTo(Money other) => Pence.CompareTo(other.Pence);

    public static Money operator +(Money a, Money b) => new(checked(a.Pence + b.Pence));

    public static Money operator -(Money a, Money b) => new(checked(a.Pence - b.Pence));

    public static bool operator <(Money a, Money b) => a.Pence < b.Pence;

    public static bool operator >(Money a, Money b) => a.Pence > b.Pence;

    public static bool operator <=(Money a, Money b) => a.Pence <= b.Pence;

    public static bool operator >=(Money a, Money b) => a.Pence >= b.Pence;

    public override string ToString() =>
        string.Create(CultureInfo.InvariantCulture, $"{(Pence < 0 ? "-" : "")}£{Math.Abs(Pence) / 100:N0}.{Math.Abs(Pence) % 100:00}");
}
