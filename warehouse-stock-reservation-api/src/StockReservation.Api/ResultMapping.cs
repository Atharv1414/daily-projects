using StockReservation.Domain;

namespace StockReservation.Api;

/// <summary>Translates domain errors into RFC 9457 problem responses with stable error codes.</summary>
public static class ResultMapping
{
    public static IResult ToProblem(this DomainError error)
    {
        var status = error.Kind switch
        {
            ErrorKind.Validation => StatusCodes.Status400BadRequest,
            ErrorKind.NotFound => StatusCodes.Status404NotFound,
            ErrorKind.Conflict => StatusCodes.Status409Conflict,
            ErrorKind.InsufficientStock => StatusCodes.Status409Conflict,
            ErrorKind.InvalidState => StatusCodes.Status422UnprocessableEntity,
            _ => StatusCodes.Status500InternalServerError,
        };
        return Results.Problem(
            title: error.Code,
            detail: error.Message,
            statusCode: status,
            extensions: new Dictionary<string, object?> { ["code"] = error.Code, ["kind"] = error.Kind.ToString() });
    }

    public static IResult ToHttp<T>(this Result<T> result, Func<T, IResult> onSuccess) =>
        result.IsSuccess ? onSuccess(result.Value!) : result.Error!.ToProblem();
}
