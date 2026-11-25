namespace FareEngine.Simulator;

public sealed class SimulatedClock(DateTimeOffset start) : TimeProvider
{
    private DateTimeOffset _now = start;

    public override DateTimeOffset GetUtcNow() => _now;

    public void Set(DateTimeOffset value) => _now = value > _now ? value : _now;
}
