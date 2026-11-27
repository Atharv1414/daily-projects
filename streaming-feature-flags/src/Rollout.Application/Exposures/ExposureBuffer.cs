using System.Threading.Channels;
using Microsoft.Extensions.Options;

namespace Rollout.Application.Exposures;

/// <summary>One viewer saw one variant of one flag.</summary>
public sealed record Exposure(string Environment, string FlagKey, string Variant, DateTimeOffset At);

/// <summary>
/// A bounded in-memory queue between the request path and the database. When the writer falls behind,
/// new exposures are dropped and counted rather than slowing down flag evaluation: analytics can lose a
/// little data, but a TV waiting for its home screen cannot wait for SQLite.
/// </summary>
public sealed class ExposureBuffer
{
    private readonly Channel<Exposure> _channel;
    private long _dropped;
    private long _accepted;

    public ExposureBuffer(IOptions<RolloutOptions> options)
    {
        ArgumentNullException.ThrowIfNull(options);
        _channel = Channel.CreateBounded<Exposure>(new BoundedChannelOptions(options.Value.ExposureBufferCapacity)
        {
            FullMode = BoundedChannelFullMode.Wait,
            SingleReader = true,
            SingleWriter = false,
        });
    }

    public long Dropped => Interlocked.Read(ref _dropped);

    public long Accepted => Interlocked.Read(ref _accepted);

    public int Pending => _channel.Reader.Count;

    public ChannelReader<Exposure> Reader => _channel.Reader;

    /// <summary>Never blocks. Returns how many were queued; the rest were dropped.</summary>
    public int Offer(IEnumerable<Exposure> exposures)
    {
        ArgumentNullException.ThrowIfNull(exposures);
        var queued = 0;
        foreach (var exposure in exposures)
        {
            if (_channel.Writer.TryWrite(exposure))
            {
                queued++;
                Interlocked.Increment(ref _accepted);
            }
            else
            {
                Interlocked.Increment(ref _dropped);
            }
        }

        return queued;
    }

    public void Complete() => _channel.Writer.TryComplete();
}
