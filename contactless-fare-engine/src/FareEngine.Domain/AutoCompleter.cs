namespace FareEngine.Domain;

/// <summary>
/// Fills in a missed tap when the rest of the same week makes the answer obvious, so a regular
/// commuter is not charged the maximum fare for one forgotten tap. Evidence comes only from the
/// week being rated: that keeps weeks independent, so correcting one can never ripple into others.
/// </summary>
public sealed class AutoCompleter(TariffBook tariffs)
{
    public IReadOnlyList<Journey> Apply(IReadOnlyList<Journey> journeys, DateOnly weekStart)
    {
        ArgumentNullException.ThrowIfNull(journeys);
        var tariff = tariffs.On(weekStart);
        var evidence = journeys
            .Where(j => j is { Mode: TravelMode.Rail, Status: JourneyStatus.Complete })
            .ToList();
        var left = tariff.AutoCompletionsPerWeek;
        var result = new List<Journey>(journeys.Count);
        foreach (var journey in journeys)
        {
            var partner = left > 0 ? Infer(journey, evidence, tariff.AutoCompletionEvidence) : null;
            if (partner is null)
            {
                result.Add(journey);
                continue;
            }

            left--;
            var exitMissing = journey.Status == JourneyStatus.MissingExit;
            result.Add(journey with
            {
                Status = JourneyStatus.AutoCompleted,
                OriginId = exitMissing ? journey.OriginId : partner,
                DestinationId = exitMissing ? partner : journey.OriginId,
                Note = $"Completed automatically: {partner} matches this week's other journeys.",
            });
        }

        return result;
    }

    private static string? Infer(Journey journey, List<Journey> evidence, int needed)
    {
        if (journey.Status is not (JourneyStatus.MissingExit or JourneyStatus.MissingEntry))
        {
            return null;
        }

        // Journeys count in both directions: the way home is evidence about the way out.
        var partners = evidence
            .Where(e => e.OriginId == journey.OriginId || e.DestinationId == journey.OriginId)
            .Where(e => e.OriginId != e.DestinationId)
            .GroupBy(e => e.OriginId == journey.OriginId ? e.DestinationId! : e.OriginId, StringComparer.Ordinal)
            .Select(g => (Place: g.Key, Count: g.Count()))
            .OrderByDescending(g => g.Count)
            .ThenBy(g => g.Place, StringComparer.Ordinal)
            .ToList();
        var total = partners.Sum(p => p.Count);

        // Enough examples, and a clear majority of them.
        return partners.Count > 0 && partners[0].Count >= needed && partners[0].Count * 5 >= total * 4
            ? partners[0].Place
            : null;
    }
}
