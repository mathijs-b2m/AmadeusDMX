// Finds Amadeus Link (the DJ laptop's companion) on the network: DNS-SD _amadeuslink._tcp (Bonjour on the Mac,
// Windows's own DNS-SD here; the browsing itself is an IServiceBrowser so tests can fake it).
using System.Text.Json;

namespace AmadeusKit;

/// Browses for services of one type and reports the instance names it sees (on any thread).
public interface IServiceBrowser
{
    /// The names now there, every time they change.
    event Action<IReadOnlyCollection<string>>? Changed;
    /// Browsing started (true) or failed / stopped (false).
    event Action<bool>? Searching;
    void Start(string type);
    void Stop();
}

public sealed class LinkBrowser : Observable
{
    public sealed record DJ(string Name)
    {
        public string Id => Name;
    }

    public const string ServiceType = "_amadeuslink._tcp";

    IReadOnlyList<DJ> _found = [];
    bool _searching;
    public IReadOnlyList<DJ> Found { get => _found; private set => Set(ref _found, value); }
    public bool Searching { get => _searching; private set => Set(ref _searching, value); }

    readonly IServiceBrowser _browser;
    readonly UIThread _ui;
    bool _started;

    /// `browser`: DNS-SD on Windows by default (nothing elsewhere).
    public LinkBrowser(IServiceBrowser? browser = null, SynchronizationContext? context = null)
    {
        _browser = browser ?? (OperatingSystem.IsWindows() ? new DnsSdBrowser() : new NoBrowser());
        _ui = new UIThread(context ?? SynchronizationContext.Current);
        _browser.Changed += names => _ui.Post(() =>
        {
            var list = names.Distinct().Order(StringComparer.Ordinal).Select(n => new DJ(n)).ToList();
            if (!list.SequenceEqual(Found)) Found = list;
        });
        _browser.Searching += on => _ui.Post(() => Searching = on && _started);
    }

    public void Start()
    {
        if (_started) return;
        _started = true;
        _browser.Start(ServiceType);
    }

    public void Stop()
    {
        _browser.Stop();
        _started = false;
        Searching = false;
    }

    sealed class NoBrowser : IServiceBrowser
    {
        public event Action<IReadOnlyCollection<string>>? Changed { add { } remove { } }
        public event Action<bool>? Searching { add { } remove { } }
        public void Start(string type) { }
        public void Stop() { }
    }
}

/// The link's health as the engine reports it in each frame.
public sealed record LinkStatus
{
    public string Name { get; init; } = "";
    public bool Up { get; init; }
    public double OffsetMs { get; init; }
    public double JitterMs { get; init; }
    public int Lost { get; init; }
    public int Packets { get; init; }
    public IReadOnlyList<string> Fetching { get; init; } = [];

    public static LinkStatus From(JsonElement c) => new()
    {
        Name = J.Req(c, "name", J.String), Up = J.Req(c, "up", J.Bool), OffsetMs = J.Req(c, "offset_ms", J.Double),
        JitterMs = J.Req(c, "jitter_ms", J.Double), Lost = J.Req(c, "lost", J.Int), Packets = J.Req(c, "packets", J.Int),
        Fetching = J.Req(c, "fetching", J.ArrayOf(J.String)),
    };

    public bool Equals(LinkStatus? o) => o is not null && Name == o.Name && Up == o.Up && OffsetMs == o.OffsetMs
        && JitterMs == o.JitterMs && Lost == o.Lost && Packets == o.Packets && Fetching.SequenceEqual(o.Fetching);

    public override int GetHashCode() => HashCode.Combine(Name, Up, Packets);
}
