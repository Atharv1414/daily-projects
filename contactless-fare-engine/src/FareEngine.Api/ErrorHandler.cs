using FareEngine.Application.Settlement;
using FareEngine.Application.Taps;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;

namespace FareEngine.Api;

/// <summary>Turns expected failures into problem details. Anything else stays a plain 500.</summary>
public sealed class ErrorHandler(IProblemDetailsService problems) : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext httpContext, Exception exception, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(httpContext);
        int? status = exception switch
        {
            SettlementNotReadyException => StatusCodes.Status409Conflict,
            BatchTooLargeException => StatusCodes.Status413PayloadTooLarge,
            BadHttpRequestException e => e.StatusCode,
            _ => null,
        };
        if (status is null)
        {
            return false;
        }

        httpContext.Response.StatusCode = status.Value;
        return await problems.TryWriteAsync(new ProblemDetailsContext
        {
            HttpContext = httpContext,
            ProblemDetails = new ProblemDetails { Status = status, Detail = exception.Message },
        });
    }
}
