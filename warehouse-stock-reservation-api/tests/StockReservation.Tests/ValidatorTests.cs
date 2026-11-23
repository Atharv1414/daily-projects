using StockReservation.Api.Auth;
using StockReservation.Application.Reservations;

namespace StockReservation.Tests;

public class ValidatorTests
{
    private static CreateReservationCommand Valid() =>
        new("ORD-1", "MAN1", [new ReservationLineRequest("KIT-1", 2)], "idem-key-1");

    public static TheoryData<CreateReservationCommand, string> InvalidCommands => new()
    {
        { Valid() with { IdempotencyKey = "short" }, "idempotency_key.invalid" },
        { Valid() with { OrderReference = " " }, "order_reference.invalid" },
        { Valid() with { WarehouseCode = "TOO-LONG-CODE" }, "warehouse.invalid" },
        { Valid() with { Lines = [] }, "lines.empty" },
        { Valid() with { Lines = [new ReservationLineRequest("KIT-1", 0)] }, "line.quantity_invalid" },
        { Valid() with { Lines = [new ReservationLineRequest("KIT-1", 1), new ReservationLineRequest("kit-1", 2)] }, "lines.duplicate_sku" },
        { Valid() with { HoldMinutes = 5000 }, "hold.invalid" },
    };

    [Theory]
    [MemberData(nameof(InvalidCommands))]
    public void Validate_RejectsInvalidCommands(CreateReservationCommand command, string expectedCode)
    {
        Assert.Equal(expectedCode, CreateReservationValidator.Validate(command, 50, 240)!.Code);
    }

    [Fact]
    public void Validate_RejectsTooManyLines()
    {
        var lines = Enumerable.Range(0, 51).Select(i => new ReservationLineRequest($"SKU-{i}", 1)).ToList();
        Assert.Equal("lines.too_many", CreateReservationValidator.Validate(Valid() with { Lines = lines }, 50, 240)!.Code);
    }

    [Fact]
    public void Fingerprint_IgnoresLineOrderAndSkuCase()
    {
        var a = Valid() with { Lines = [new("KIT-1", 2), new("TOY-9", 1)] };
        var b = Valid() with { Lines = [new("toy-9", 1), new("kit-1", 2)] };
        var c = Valid() with { Lines = [new("KIT-1", 3), new("TOY-9", 1)] };
        Assert.Equal(CreateReservationValidator.Fingerprint(a), CreateReservationValidator.Fingerprint(b));
        Assert.NotEqual(CreateReservationValidator.Fingerprint(a), CreateReservationValidator.Fingerprint(c));
    }

    [Fact]
    public void PasswordHasher_RoundTripsAndRejectsTampering()
    {
        var hash = PasswordHasher.Hash("correct horse");
        Assert.True(PasswordHasher.Verify("correct horse", hash));
        Assert.False(PasswordHasher.Verify("wrong horse", hash));
        Assert.False(PasswordHasher.Verify("correct horse", "md5$abc"));
        Assert.False(PasswordHasher.Verify("correct horse", "pbkdf2-sha256$1000$!!notbase64$xx"));
    }
}
