// The live feed client: connects to the engine's WebSocket (ws://127.0.0.1:8765 by default), keeps
// reconnecting, and keeps the last hello + frame.
//
// Frames (40 a second) are received and decoded off the UI thread: if they were decoded on it, every busy
// moment of the UI (layout, the inspector) would hold them up and the show would stutter. The renderer reads
// `LatestFrame` (thread-safe) every display frame; the UI observes the slower properties, updated a few times a
// second on the SynchronizationContext the feed was made on.
using System.Buffers;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;

namespace AmadeusKit;

public enum FeedState { Idle, Connecting, Connected }

public sealed class LiveFeed : Observable, IDisposable
{
    FeedState _state = FeedState.Idle;
    Hello? _hello;
    double _time;
    int _phrase;
    IReadOnlyList<DeckInfo> _decks = [];
    IReadOnlyDictionary<string, string> _laserGuard = new Dictionary<string, string>();
    LinkStatus? _link;
    double _fps;
    ArcStatus? _arc;

    public FeedState State { get => _state; private set => Set(ref _state, value); }
    public Hello? Hello { get => _hello; private set => Set(ref _hello, value); }
    /// Updated a few times a second for the UI.
    public double Time { get => _time; private set => Set(ref _time, value); }
    public int Phrase { get => _phrase; private set => Set(ref _phrase, value); }
    public IReadOnlyList<DeckInfo> Decks { get => _decks; private set => Set(ref _decks, value); }
    /// The laser guard's latest actions (laser id → what it did).
    public IReadOnlyDictionary<string, string> LaserGuard { get => _laserGuard; private set => Set(ref _laserGuard, value); }
    /// VirtualDJ on another computer (Amadeus Link): the link's health, else nil.
    public LinkStatus? Link { get => _link; private set => Set(ref _link, value); }
    /// Frames per second actually received.
    public double Fps { get => _fps; private set => Set(ref _fps, value); }
    /// Live mode: the show arc (the night's stage and knobs), else nil.
    public ArcStatus? Arc { get => _arc; private set => Set(ref _arc, value); }

    /// The newest frame (any thread may read it; the receiver writes it).
    readonly Lock _box = new();
    Frame? _latest;
    DateTime _arrival = DateTime.MinValue;
    public Frame? LatestFrame { get { lock (_box) return _latest; } }
    public DateTime LatestFrameArrival { get { lock (_box) return _arrival; } }

    /// The newest frame, when it carries the fixtures (not a lite status frame).
    public Frame? LatestFullFrame => LatestFrame is { Lite: false } f ? f : null;

    /// True while frames keep arriving (the engine is sending, i.e. a show runs).
    public bool IsReceiving => (DateTime.UtcNow - LatestFrameArrival).TotalSeconds < 1.5;

    readonly UIThread _ui;
    CancellationTokenSource? _loop;
    /// The open connection, to talk back to the engine (the show arc's controls).
    ClientWebSocket? _socket;
    readonly SemaphoreSlim _sending = new(1, 1);

    public Uri Url { get; }

    bool _lite;
    /// Status frames only, a few a second (Perform mode: no 3D stage to feed). Reconnects when it changes.
    public bool Lite
    {
        get => _lite;
        set
        {
            if (!Set(ref _lite, value) || _loop is null) return;
            Stop();
            lock (_box) { _latest = null; _arrival = DateTime.MinValue; }  // a lite frame has no fixtures: never hand it to the renderer
            Start();
        }
    }

    /// `context`: where the properties change (the UI thread); by default the one this feed is made on.
    public LiveFeed(Uri? url = null, SynchronizationContext? context = null)
    {
        Url = url ?? new Uri("ws://127.0.0.1:8765");
        _ui = new UIThread(context ?? SynchronizationContext.Current);
    }

    public void Start()
    {
        if (_loop is not null) return;
        var cts = new CancellationTokenSource();
        _loop = cts;
        var url = Lite ? new Uri(Url, Url.AbsolutePath.TrimEnd('/') + "/lite") : Url;
        _ = Task.Run(async () =>
        {
            while (!cts.IsCancellationRequested)
            {
                await Receive(url, cts.Token);
                try { await Task.Delay(TimeSpan.FromSeconds(1), cts.Token); }
                catch (OperationCanceledException) { }
            }
        });
    }

    public void Stop()
    {
        _loop?.Cancel();
        _loop = null;
        State = FeedState.Idle;
    }

    public void Dispose() => Stop();

    /// Tell the engine something (a JSON object), e.g. `new { type = "arc", knob = new { intensity = 0.7 } }`.
    /// Dropped when no engine is connected.
    public void Send(object message)
    {
        var socket = Volatile.Read(ref _socket);
        if (socket is not { State: WebSocketState.Open }) return;
        var bytes = JsonSerializer.SerializeToUtf8Bytes(message, message.GetType(), SetupAPI.JsonOptions);
        _ = Task.Run(async () =>
        {
            await _sending.WaitAsync();
            try { await socket.SendAsync(bytes, WebSocketMessageType.Text, true, CancellationToken.None); }
            catch (Exception e) when (e is WebSocketException or ObjectDisposedException or InvalidOperationException) { }
            finally { _sending.Release(); }
        });
    }

    /// One connection: receive until it drops. Runs off the UI thread.
    async Task Receive(Uri url, CancellationToken ct)
    {
        _ui.Post(() => { if (_loop is not null) State = FeedState.Connecting; });
        using var socket = new ClientWebSocket();
        var buffer = ArrayPool<byte>.Shared.Rent(1 << 16);
        var message = new MemoryStream();
        var connected = false;
        int count = 0, lastPhrase = -1;
        DateTime since = DateTime.UtcNow, lastUI = DateTime.MinValue;
        try
        {
            await socket.ConnectAsync(url, ct);
            Volatile.Write(ref _socket, socket);
            while (!ct.IsCancellationRequested)
            {
                message.SetLength(0);
                WebSocketReceiveResult r;
                do
                {
                    r = await socket.ReceiveAsync(buffer, ct);
                    if (r.MessageType == WebSocketMessageType.Close) return;
                    message.Write(buffer, 0, r.Count);
                    if (message.Length > 16 << 20) return;  // nothing the engine sends is this big
                } while (!r.EndOfMessage);
                if (!connected)
                {
                    connected = true;
                    _ui.Post(() => { if (_loop is not null) State = FeedState.Connected; });
                }
                switch (FeedMessage.Decode(message.GetBuffer().AsSpan(0, (int)message.Length)))
                {
                    case HelloMessage { Hello: var h }:
                        _ui.Post(() => Hello = h);
                        break;
                    case FrameMessage { Frame: var f }:
                        var now = DateTime.UtcNow;
                        lock (_box) { _latest = f; _arrival = now; }
                        count++;
                        double? fps = null;
                        if ((now - since).TotalSeconds >= 1)
                        {
                            fps = count / (now - since).TotalSeconds;
                            count = 0; since = now;
                            if (Defaults.Standard.Bool("gpuStats"))  // development: what the counter shows
                                try { File.AppendAllText(Path.Combine(Path.GetTempPath(), "gpu-stats.txt"), $"feed counter {fps:F1} fps\n"); }
                                catch (IOException) { }
                        }
                        // the UI: a few times a second, or at once when the phrase changes
                        if ((now - lastUI).TotalSeconds >= 0.2 || f.Phrase != lastPhrase || fps is not null)
                        {
                            lastUI = now; lastPhrase = f.Phrase;
                            // hand the UI its update without waiting: a busy UI thread must never hold up the frames
                            _ui.Post(() => Update(f, fps));
                        }
                        break;
                }
            }
        }
        catch (Exception e) when (e is WebSocketException or OperationCanceledException or IOException or HttpRequestException)
        {
            // engine not running (yet) or it went away: try again
        }
        finally
        {
            Interlocked.CompareExchange(ref _socket, null, socket);
            ArrayPool<byte>.Shared.Return(buffer);
            if (socket.State == WebSocketState.Open)
                try { await socket.CloseOutputAsync(WebSocketCloseStatus.EndpointUnavailable, null, CancellationToken.None); }
                catch (Exception e) when (e is WebSocketException or ObjectDisposedException) { }
            _ui.Post(() => { if (_loop is not null) State = FeedState.Connecting; });
        }
    }

    void Update(Frame f, double? fps)
    {
        if (f.Link != Link) Link = f.Link;
        if (f.Arc != Arc) Arc = f.Arc;
        Time = f.T;
        Phrase = f.Phrase;
        if (f.Decks is { } d && !d.SequenceEqual(Decks)) Decks = d;
        var g = f.LaserGuard ?? new Dictionary<string, string>();
        if (g.Count != LaserGuard.Count || g.Any(p => !LaserGuard.TryGetValue(p.Key, out var v) || v != p.Value)) LaserGuard = g;
        if (fps is { } x) Fps = x;
    }
}
