using System.Text.Json;
using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using Rollout.Api.Endpoints;
using Rollout.Application;

namespace Rollout.Api;

/// <summary>Turns expected failures into RFC 9457 problem details. Anything else stays a plain 500.</summary>
public sealed class ErrorHandler(IProblemDetailsService problems) : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext httpContext, Exception exception, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(httpContext);
        int? status = exception switch
        {
            UnknownEnvironmentException or FlagNotFoundException => StatusCodes.Status404NotFound,
            ForbiddenEnvironmentException => StatusCodes.Status403Forbidden,
            FlagValidationException => StatusCodes.Status400BadRequest,
            VersionConflictException => StatusCodes.Status412PreconditionFailed,
            VersionRequiredException => StatusCodes.Status428PreconditionRequired,
            FlagInUseException or NotAnExperimentException => StatusCodes.Status409Conflict,
            ArgumentException or JsonException => StatusCodes.Status400BadRequest,
            BadHttpRequestException e => e.StatusCode,
            _ => null,
        };
        if (status is null)
        {
            return false;
        }

        var details = new ProblemDetails { Status = status, Detail = exception.Message };
        if (exception is FlagValidationException validation)
        {
            details.Title = "The flag definition is not valid";
            details.Extensions["errors"] = validation.Errors;
        }

        if (exception is VersionConflictException conflict)
        {
            details.Extensions["currentVersion"] = conflict.Current;
            httpContext.Response.Headers.ETag = Http.VersionTag(conflict.Current);
        }

        httpContext.Response.StatusCode = status.Value;
        return await problems.TryWriteAsync(new ProblemDetailsContext { HttpContext = httpContext, ProblemDetails = details });
    }
}

public static class Http
{
    public static string VersionTag(long version) => $"\"{version}\"";

    /// <summary>Reads <c>If-Match: "7"</c> (or <c>W/"7"</c>). Returns null when the header is absent.</summary>
    public static long? IfMatchVersion(HttpRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        var header = request.Headers.IfMatch.ToString();
        if (string.IsNullOrWhiteSpace(header))
        {
            return null;
        }

        var text = header.Trim();
        if (text.StartsWith("W/", StringComparison.Ordinal))
        {
            text = text[2..];
        }

        return long.TryParse(text.Trim('"'), System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out var version)
            ? version
            : throw new BadHttpRequestException("If-Match must be a flag version such as \"3\".");
    }
}
