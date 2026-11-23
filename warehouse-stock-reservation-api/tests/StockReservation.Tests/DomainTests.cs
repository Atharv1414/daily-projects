using StockReservation.Domain;

namespace StockReservation.Tests;

public class StockItemTests
{
    private static readonly DateTimeOffset Now = TestDb.Start;

    private static StockItem Item(int onHand = 10, int reorder = 2) => new("MAN1", "KIT-1", "Kettle", onHand, reorder, 1999, Now);

    [Fact]
    public void Reserve_ReducesAvailableAndBumpsVersion()
    {
        var item = Item();
        Assert.True(item.Reserve(4, Now).IsSuccess);
        Assert.Equal(6, item.Available);
        Assert.Equal(4, item.Reserved);
        Assert.Equal(1, item.Version);
    }

    [Theory]
    [InlineData(0, ErrorKind.Validation)]
    [InlineData(-3, ErrorKind.Validation)]
    [InlineData(11, ErrorKind.InsufficientStock)]
    public void Reserve_RejectsBadQuantities(int quantity, ErrorKind expected)
    {
        var item = Item();
        var result = item.Reserve(quantity, Now);
        Assert.Equal(expected, result.Error!.Kind);
        Assert.Equal(0, item.Version);
    }

    [Fact]
    public void Allocate_RemovesFromOnHandAndReserved()
    {
        var item = Item();
        item.Reserve(5, Now);
        Assert.True(item.Allocate(5, Now).IsSuccess);
        Assert.Equal(5, item.OnHand);
        Assert.Equal(0, item.Reserved);
    }

    [Fact]
    public void Release_CannotExceedReserved()
    {
        var item = Item();
        item.Reserve(2, Now);
        Assert.Equal(ErrorKind.InvalidState, item.Release(3, Now).Error!.Kind);
    }

    [Fact]
    public void Adjust_CannotGoBelowReserved()
    {
        var item = Item();
        item.Reserve(8, Now);
        Assert.Equal("adjustment.below_reserved", item.Adjust(-3, Now).Error!.Code);
        Assert.True(item.Adjust(-2, Now).IsSuccess);
        Assert.Equal(0, item.Available);
    }

    [Fact]
    public void Receive_GuardsAgainstOverflow()
    {
        var item = Item(onHand: int.MaxValue - 1);
        Assert.Equal("quantity.overflow", item.Receive(5, Now).Error!.Code);
    }

    [Fact]
    public void RandomOperationSequences_PreserveInvariants()
    {
        // Model-based property test: thousands of random operations never break 0 <= Reserved <= OnHand.
        for (var seed = 0; seed < 200; seed++)
        {
            var random = new Random(seed);
            var item = Item(onHand: random.Next(0, 50));
            for (var step = 0; step < 50; step++)
            {
                var qty = random.Next(-5, 15);
                _ = random.Next(5) switch
                {
                    0 => item.Reserve(qty, Now),
                    1 => item.Release(qty, Now),
                    2 => item.Allocate(qty, Now),
                    3 => item.Receive(qty, Now),
                    _ => item.Adjust(qty, Now),
                };
                Assert.InRange(item.Reserved, 0, item.OnHand);
                Assert.True(item.OnHand >= 0);
            }
        }
    }
}

public class ReservationStateTests
{
    private static readonly DateTimeOffset Now = TestDb.Start;

    private static Reservation Pending() =>
        new("ORD-1", "MAN1", [new ReservationLine("KIT-1", 2)], "key-12345", "fp", "planner", Now, TimeSpan.FromMinutes(30));

    [Fact]
    public void Confirm_FromPending_Succeeds()
    {
        var r = Pending();
        Assert.True(r.Confirm(Now.AddMinutes(5)).IsSuccess);
        Assert.Equal(ReservationStatus.Confirmed, r.Status);
        Assert.Equal(Now.AddMinutes(5), r.ClosedAt);
    }

    [Fact]
    public void Confirm_AfterHoldExpires_Fails()
    {
        Assert.Equal("reservation.expired", Pending().Confirm(Now.AddMinutes(30)).Error!.Code);
    }

    [Fact]
    public void Expire_BeforeDue_Fails()
    {
        Assert.Equal("reservation.not_due", Pending().Expire(Now.AddMinutes(29)).Error!.Code);
    }

    [Theory]
    [InlineData("confirm")]
    [InlineData("release")]
    [InlineData("expire")]
    public void ClosedReservation_CannotTransitionAgain(string second)
    {
        var r = Pending();
        r.Release(Now);
        var later = Now.AddHours(1);
        var result = second switch
        {
            "confirm" => r.Confirm(later),
            "release" => r.Release(later),
            _ => r.Expire(later),
        };
        Assert.Equal("reservation.invalid_transition", result.Error!.Code);
    }
}

public class OutboxMessageTests
{
    [Fact]
    public void MarkFailed_BacksOffExponentiallyThenDeadLetters()
    {
        var now = TestDb.Start;
        var m = new OutboxMessage("t", "{}", now);
        m.MarkFailed("boom", now, maxAttempts: 4, TimeSpan.FromSeconds(10));
        Assert.Equal(now.AddSeconds(10), m.NextAttemptAt);
        m.MarkFailed("boom", now, 4, TimeSpan.FromSeconds(10));
        Assert.Equal(now.AddSeconds(20), m.NextAttemptAt);
        m.MarkFailed("boom", now, 4, TimeSpan.FromSeconds(10));
        Assert.Equal(now.AddSeconds(40), m.NextAttemptAt);
        m.MarkFailed("boom", now, 4, TimeSpan.FromSeconds(10));
        Assert.Equal(OutboxStatus.DeadLettered, m.Status);
        Assert.Equal(4, m.Attempts);
    }

    [Fact]
    public void MarkFailed_TruncatesLongErrors()
    {
        var m = new OutboxMessage("t", "{}", TestDb.Start);
        m.MarkFailed(new string('x', 2000), TestDb.Start, 5, TimeSpan.FromSeconds(1));
        Assert.Equal(500, m.LastError!.Length);
    }
}
