// Amadeus Link, on the DJ's laptop: passes VirtualDJ's mix state to the lighting computer over the network.
//
// The AmadeusLink plugin in VirtualDJ sends its packets to this app (UDP 127.0.0.1:9123, as it would to a local
// engine). The app advertises itself with DNS-SD (_amadeuslink._tcp, TCP port 7123), pairs with a lighting
// computer through a 4-digit code, and forwards every packet with this laptop's clock and a signature. It serves
// the lighting computer the tracks VirtualDJ has loaded (and only those). The networking is AmadeusKit's LinkNet
// (tested against the engine's receiver); this is its state for the window.
// Protocol: docs/protocols.md (and amadeus/show/link.py, the receiving end).
namespace AmadeusLink;

public sealed class LinkServer : Observable, IDisposable
{
    /// The DJ software on this laptop: VirtualDJ sends through its plugin; djay Pro and Mixxx Amadeus Link reads itself.
    public enum Software { VirtualDJ, Djay, Mixxx }

    public static string RawValue(Software s) => s switch { Software.Djay => "djay", Software.Mixxx => "mixxx", _ => "virtualdj" };
    public static string Title(Software s) => s switch { Software.Djay => "djay Pro", Software.Mixxx => "Mixxx", _ => "VirtualDJ" };
    static Software? Parse(string? raw) => raw switch
    {
        "virtualdj" => Software.VirtualDJ, "djay" => Software.Djay, "mixxx" => Software.Mixxx, _ => null,
    };

    bool _isOn;
    string _code = LinkProtocol.NewCode();
    IReadOnlyList<LinkNet.Peer> _peers = [];
    DateTime _lastPluginPacket = DateTime.MinValue;
    string _deckSummary = "", _djApp = "VirtualDJ", _readerNote = "";
    string? _error, _pluginError;
    int _tracksServed;
    Software _software = Software.VirtualDJ;

    public bool IsOn { get => _isOn; private set => Set(ref _isOn, value); }
    public string Code { get => _code; private set => Set(ref _code, value); }
    public IReadOnlyList<LinkNet.Peer> Peers { get => _peers; private set => Set(ref _peers, value); }
    public DateTime LastPluginPacket { get => _lastPluginPacket; private set { if (Set(ref _lastPluginPacket, value)) Changed(nameof(DjConnected)); } }
    public string DeckSummary { get => _deckSummary; private set => Set(ref _deckSummary, value); }
    /// The DJ software sending the decks: the VirtualDJ plugin, or `amadeus probe NAME --emit` (which names it).
    public string DjApp { get => _djApp; private set => Set(ref _djApp, value); }
    public string? Error { get => _error; private set => Set(ref _error, value); }
    /// Why the DJ software can't reach this app (its port is taken), nil while it can. Kept apart from `Error`:
    /// switching Link on or off doesn't clear it, only listening again does.
    public string? PluginError { get => _pluginError; private set => Set(ref _pluginError, value); }
    public int TracksServed { get => _tracksServed; private set => Set(ref _tracksServed, value); }
    public Software Current { get => _software; private set => Set(ref _software, value); }
    /// What the DJ should know or do for the chosen DJ software ("" when all is well).
    public string ReaderNote { get => _readerNote; private set => Set(ref _readerNote, value); }

    CancellationTokenSource? _pump;  // the reader's: its loop owns the reader
    readonly LinkNet _net = new();
    readonly UIThread _ui = UIThread.Current();

    /// Updates (a release build only): never while a lighting computer is connected.
    public Updates Updates { get; }

    public LinkServer(IUpdater? updater)
    {
        Updates = new Updates(updater) { IsBusy = () => Peers.Count > 0 };
        var d = Defaults.Standard;
        if (d.String("code") is { Length: 4 } fixedCode) Code = fixedCode;  // -code 1234 (tests)
        _net.OnPlugin = (summary, app) => _ui.Post(() => Plugin(summary, app));
        _net.OnPeers = peers => _ui.Post(() =>
        {
            Peers = peers;
            if (peers.Count == 0) Updates.BecameIdle();  // an update that waited for the lighting computer
        });
        _net.OnError = e => _ui.Post(() => Error = e.Length == 0 ? null : e);
        _net.OnPluginError = e => _ui.Post(() => PluginError = e);
        _net.OnServed = () => _ui.Post(() => TracksServed++);
        _net.Code = Code;
        var streams = new VirtualDJStreams();  // VirtualDJ's streamed tracks, named from its database
        _net.Enrich = streams.Enrich;
        var pluginPort = d.Integer("pluginPort");  // -pluginPort 9124 (tests)
        _net.StartPlugin(pluginPort > 0 ? pluginPort : LinkProtocol.PluginPort);
        if (d.BoolIfSet("linkOn") ?? true) SetOn(true);
        SetSoftware(Parse(d.String("djSoftware")) ?? Software.VirtualDJ);
        _ = Tick();
    }

    /// "connected" fades after 1.5 s without a packet: look again every second (the Mac's TimelineView).
    async Task Tick()
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(1));
        while (await timer.WaitForNextTickAsync()) Changed(nameof(DjConnected));
    }

    /// Which DJ software to pass on. djay Pro and Mixxx are read here, 50 times a second, into the plugin's packets.
    public void SetSoftware(Software s)
    {
        Defaults.Standard.Set("djSoftware", RawValue(s));
        Current = s;
        _pump?.Cancel();
        _pump = null;
        ReaderNote = "";
        _net.PluginOn = s == Software.VirtualDJ;
        if (s == Software.VirtualDJ) return;
        var cts = _pump = new CancellationTokenSource();
        _ = Task.Run(async () =>
        {
            IDJReader r;
            try { r = Readers.Make(s); }  // off the UI thread: a MIDI port may take a moment
            catch (Exception e) when (e is not OutOfMemoryException)
            {
                _ui.Post(() => { if (_pump == cts) ReaderNote = $"{Title(s)} can't be read: {e.Message}"; });
                return;
            }
            var start = Clock.Monotonic();
            var noted = 0.0;
            using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(20));
            try
            {
                do
                {
                    var now = Clock.Monotonic();
                    var decks = r.Decks(now);
                    if (decks.Count > 0) _net.Send(Packet.Make(r.App, decks, now, start));
                    if (now - noted <= 0.5) continue;
                    noted = now;
                    var (note, summary) = (r.Note, r.Summary(now));
                    _ui.Post(() =>
                    {
                        if (_pump != cts) return;
                        ReaderNote = note;
                        DeckSummary = summary;  // every deck, also those not passed on
                    });
                }
                while (await timer.WaitForNextTickAsync(cts.Token));
            }
            catch (OperationCanceledException) { }
            finally { r.Stop(); }
        });
    }

    public bool DjConnected => (DateTime.UtcNow - LastPluginPacket).TotalSeconds < 1.5;

    public void SetOn(bool on)
    {
        Defaults.Standard.Set("linkOn", on);
        IsOn = on;
        Error = null;
        if (on) _net.StartService(LinkProtocol.ServicePort, Environment.MachineName);
        else _net.StopService();
    }

    public void RenewCode()
    {
        Code = LinkProtocol.NewCode();
        _net.Code = Code;
    }

    public void Disconnect(string id) => _net.Drop(id);

    void Plugin(string summary, string app)
    {
        LastPluginPacket = DateTime.UtcNow;
        if (Current == Software.VirtualDJ) DeckSummary = summary;  // a reader of our own writes its own (every deck)
        DjApp = app;
    }

    public void Dispose()
    {
        _pump?.Cancel();
        _net.Dispose();
    }
}
