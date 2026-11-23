using StockReservation.Api.Auth;

namespace StockReservation.Api.Endpoints;

public static class AuthEndpoints
{
    public static IEndpointRouteBuilder MapAuthEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/auth/token", (TokenRequest request, TokenService tokens) =>
            {
                if (string.IsNullOrWhiteSpace(request.Username) || string.IsNullOrEmpty(request.Password))
                {
                    return Results.Problem(title: "auth.invalid_request", statusCode: StatusCodes.Status400BadRequest);
                }

                var token = tokens.Issue(request.Username, request.Password);
                return token is null
                    ? Results.Problem(title: "auth.invalid_credentials", statusCode: StatusCodes.Status401Unauthorized)
                    : Results.Ok(token);
            })
            .WithTags("Auth")
            .WithSummary("Exchange demo credentials for a bearer token")
            .RequireRateLimiting(RateLimitPolicies.Auth)
            .AllowAnonymous();
        return app;
    }
}
