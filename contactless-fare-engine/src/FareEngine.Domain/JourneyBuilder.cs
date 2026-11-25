namespace FareEngine.Domain;

/// <summary>
/// Turns one card's taps into journeys. A pure function of the set of taps and the clock:
/// it sorts first, so the order in which readers delivered them cannot change the answer.
/// </summary>
public sealed class JourneyBuilder(Network network, TariffBook tariffs)
{
    public IReadOnlyList<Journey> Build(IEnumerable<Tap> taps, DateTimeOffset asOf)
    {
        ArgumentNullException.ThrowIfNull(taps);
        var state = new State();
        foreach (var tap in taps.DistinctBy(t => t.Id).Order(Tap.Chronological))
        {
            var tariff = tariffs.On(ServiceCalendar.ServiceDate(tap.OccurredAt));
            if (IsPassback(state.LastTap, tap, tariff))
            {
                continue;
            }

            switch (tap.Kind)
            {
                case TapKind.Entry:
                    Enter(state, tap, tariff);
                    break;
                case TapKind.Exit:
                    Exit(state, tap, tariff);
                    break;
                case TapKind.Board:
                    Board(state, tap, tariff);
                    break;
                default:
                    throw new InvalidOperationException($"Unhandled tap kind {tap.Kind}.");
            }

            state.LastTap = tap;
        }

        if (state.Open is { } open)
        {
            var limit = tariffs.On(open.ServiceDate).MaximumJourney;
            var expired = asOf - open.StartedAt > limit;
            state.Done.Add(expired
                ? open with { Status = JourneyStatus.MissingExit, Note = "No exit was recorded." }
                : open);
        }

        return [.. state.Done.OrderBy(j => j.StartedAt).ThenBy(j => j.TapIds[0])];
    }

    /// <summary>The same card on the same reader within a minute is one presentation, not two.</summary>
    private static bool IsPassback(Tap? previous, Tap tap, Tariff tariff) =>
        previous is not null
        && previous.PlaceId == tap.PlaceId
        && previous.Kind == tap.Kind
        && tap.OccurredAt - previous.OccurredAt < tariff.PassbackWindow;

    private void Enter(State state, Tap tap, Tariff tariff)
    {
        if (state.Open is not null)
        {
            state.CloseWithoutExit();
        }
        else if (TryContinue(state, tap, tariff) is { } continued)
        {
            state.Done.RemoveAt(state.Done.Count - 1);
            state.Open = continued;
            return;
        }

        state.Open = new Journey
        {
            Mode = TravelMode.Rail,
            Status = JourneyStatus.InProgress,
            OriginId = tap.PlaceId,
            StartedAt = tap.OccurredAt,
            TapIds = [tap.Id],
        };
    }

    /// <summary>Walking between linked stations carries on the same journey, if it is still within the time limit.</summary>
    private Journey? TryContinue(State state, Tap tap, Tariff tariff)
    {
        if (state.Done.Count == 0 || state.Done[^1] is not { Status: JourneyStatus.Complete, Mode: TravelMode.Rail } last)
        {
            return null;
        }

        var limit = network.InterchangeLimit(last.DestinationId!, tap.PlaceId);
        return limit is { } allowed
            && tap.OccurredAt - last.EndedAt!.Value <= allowed
            && tap.OccurredAt - last.StartedAt <= tariff.MaximumJourney
            ? last with
            {
                Status = JourneyStatus.InProgress,
                DestinationId = null,
                EndedAt = null,
                Interchanges = last.Interchanges + 1,
                TapIds = [.. last.TapIds, tap.Id],
            }
            : null;
    }

    private static void Exit(State state, Tap tap, Tariff tariff)
    {
        if (state.Open is not { } open)
        {
            state.Done.Add(MissingEntry(tap, "No entry was recorded."));
            return;
        }

        state.Open = null;
        var elapsed = tap.OccurredAt - open.StartedAt;
        if (elapsed > tariff.MaximumJourney)
        {
            state.Done.Add(open with { Status = JourneyStatus.TooLong, Note = "Longer than the maximum journey time." });
            state.Done.Add(MissingEntry(tap, "The matching entry was too long ago."));
            return;
        }

        var changedMind = tap.PlaceId == open.OriginId && open.Interchanges == 0 && elapsed <= tariff.SameStationGrace;
        state.Done.Add(open with
        {
            Status = changedMind ? JourneyStatus.SameStation : JourneyStatus.Complete,
            DestinationId = tap.PlaceId,
            EndedAt = tap.OccurredAt,
            TapIds = [.. open.TapIds, tap.Id],
            Note = changedMind ? "Left the same station within the grace period: no charge." : null,
        });
    }

    private static void Board(State state, Tap tap, Tariff tariff)
    {
        if (state.Open is not null)
        {
            state.CloseWithoutExit();
        }

        var date = ServiceCalendar.ServiceDate(tap.OccurredAt);
        var free = state.HopperStart is { } start
            && ServiceCalendar.ServiceDate(start) == date
            && tap.OccurredAt - start <= tariff.HopperWindow;
        if (!free)
        {
            state.HopperStart = tap.OccurredAt;
        }

        state.Done.Add(new Journey
        {
            Mode = TravelMode.Bus,
            Status = JourneyStatus.Complete,
            OriginId = tap.PlaceId,
            StartedAt = tap.OccurredAt,
            EndedAt = tap.OccurredAt,
            TapIds = [tap.Id],
            HopperFree = free,
            Note = free ? "Free transfer within the hopper window." : null,
        });
    }

    private static Journey MissingEntry(Tap tap, string note) => new()
    {
        Mode = TravelMode.Rail,
        Status = JourneyStatus.MissingEntry,
        OriginId = tap.PlaceId,
        StartedAt = tap.OccurredAt,
        EndedAt = tap.OccurredAt,
        TapIds = [tap.Id],
        Note = note,
    };

    private sealed class State
    {
        public List<Journey> Done { get; } = [];

        public Journey? Open { get; set; }

        public DateTimeOffset? HopperStart { get; set; }

        public Tap? LastTap { get; set; }

        public void CloseWithoutExit()
        {
            Done.Add(Open! with { Status = JourneyStatus.MissingExit, Note = "No exit was recorded." });
            Open = null;
        }
    }
}
