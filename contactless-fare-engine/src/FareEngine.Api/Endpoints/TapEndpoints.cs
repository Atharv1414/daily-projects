using System.Text.Json;
using FareEngine.Api.Auth;
using FareEngine.Application.Taps;
using Microsoft.AspNetCore.Http.Json;
using Microsoft.Extensions.Options;

namespace FareEngine.Api.Endpoints;

public static class TapEndpoints
{
    private const int MaxBodyBytes = 256 * 1024;

    public static void MapTaps(this IEndpointRouteBuilder app) =>
        app.MapPost("/v1/taps", PostAsync)
            .Accepts<TapBatch>("application/json")
            .Produces<TapBatchResult>()
            .ProducesProblem(StatusCodes.Status401Unauthorized)
            .ProducesProblem(StatusCodes.Status413PayloadTooLarge)
            .WithSummary("Reader batch upload, signed with HMAC-SHA256. Safe to retry.")
            .WithTags("Readers");

    private static async Task<IResult> PostAsync(
        HttpRequest request, ReaderSignature signature, TapIngestion ingestion, IOptions<JsonOptions> json, CancellationToken ct)
    {
        // The signature covers raw bytes, so the body is read before it is parsed.
        var body = await ReadBodyAsync(request, ct);
        if (body is null)
        {
            return Results.Problem("The batch is too large.", statusCode: StatusCodes.Status413PayloadTooLarge);
        }

        if (!signature.TryVerify(request.Headers, body, out var readerId))
        {
            return Results.Problem("The reader signature is missing, wrong or out of date.", statusCode: StatusCodes.Status401Unauthorized);
        }

        TapBatch? batch;
        try
        {
            batch = JsonSerializer.Deserialize<TapBatch>(body, json.Value.SerializerOptions);
        }
        catch (JsonException)
        {
            return Results.Problem("The batch is not valid JSON.", statusCode: StatusCodes.Status400BadRequest);
        }

        if (batch?.Taps is null || batch.Taps.Any(t => t is null))
        {
            return Results.Problem("The batch has no taps.", statusCode: StatusCodes.Status400BadRequest);
        }

        var results = await ingestion.IngestAsync(batch.Taps, readerId, ct: ct);
        return Results.Ok(new TapBatchResult(
            results.Count(r => r.Outcome == TapOutcome.Accepted),
            results.Count(r => r.Outcome == TapOutcome.Duplicate),
            results.Count(r => r.Outcome == TapOutcome.Conflict),
            results.Count(r => r.Outcome == TapOutcome.Rejected),
            results));
    }

    private static async Task<byte[]?> ReadBodyAsync(HttpRequest request, CancellationToken ct)
    {
        using var buffer = new MemoryStream();
        var chunk = new byte[16 * 1024];
        int read;
        while ((read = await request.Body.ReadAsync(chunk, ct)) > 0)
        {
            if (buffer.Length + read > MaxBodyBytes)
            {
                return null;
            }

            buffer.Write(chunk, 0, read);
        }

        return buffer.ToArray();
    }
}
