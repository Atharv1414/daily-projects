namespace StockReservation.Application.Common;

/// <summary>A page of results plus the information a client needs to request the next one.</summary>
public sealed record PagedResult<T>(IReadOnlyList<T> Items, int Page, int PageSize, int TotalCount)
{
    public int TotalPages => TotalCount == 0 ? 0 : (int)Math.Ceiling(TotalCount / (double)PageSize);

    public bool HasNext => Page < TotalPages;
}

/// <summary>Normalised paging request; out-of-range values are clamped rather than rejected.</summary>
public readonly record struct PageRequest(int Page, int PageSize)
{
    public const int MaxPageSize = 200;

    public static PageRequest Create(int? page, int? pageSize) =>
        new(Math.Max(1, page ?? 1), Math.Clamp(pageSize ?? 50, 1, MaxPageSize));

    public int Skip => (Page - 1) * PageSize;
}
